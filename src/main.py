import os                    # For file path operations
import json                  # For parsing LLM output
import re                     # For extracting numbers from damage amounts
from pdf_extraction import extract_text_from_pdf  # Direct PDF text extraction
from pathlib import Path      # Cross-platform file paths
from typing import Dict, List, Optional  # Type hints for clarity

from llama_cpp import Llama   # Local LLM engine (llama.cpp)

# ---------------------------
# 1. Configuration & LLM Setup
# ---------------------------

# Load the local Qwen model - runs offline, no API needed
llm = Llama(
    model_path=os.path.join(os.path.dirname(__file__), "model", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
    n_ctx=4096,        # Context window size (tokens)
    n_threads=8,       # CPU cores to use
    temperature=0,     # 0 = deterministic output
    verbose=False      # Suppress model loading messages
)


def run_llm(prompt: str) -> str:
    """Send prompt to local LLM with system instruction."""
    out = llm(
        f"<|system|>You are a precise information extraction and reasoning engine.\n"
        f"<|user|>{prompt}\n<|assistant|>",
        max_tokens=800,          # Limit response length
        stop=["<|user|>"]         # Stop at user token
    )
    return out["choices"][0]["text"].strip()


def run_llm_bool(prompt: str) -> bool | None:
    """Run LLM for a Yes/No question. Returns True/False or None if unsure."""
    out = llm(
        f"<|system|>Answer ONLY with 'YES' or 'NO'. No explanation.\n"
        f"<|user|>{prompt}\n<|assistant|>",
        max_tokens=10,
        stop=["<|user|>", "\n"]
    )
    text = out["choices"][0]["text"].strip().upper()
    if "YES" in text:
        return True
    if "NO" in text:
        return False
    return None


def extract_json(text: str) -> str:
    """Find and extract valid JSON object from LLM output."""
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON found in LLM output")

    try:
        # Try strict JSON parsing first
        obj, _ = json.JSONDecoder().raw_decode(text, start)
        return json.dumps(obj)
    except Exception:
        # Fallback: slice between first { and last }
        end = text.rfind("}")
        if end == -1:
             raise ValueError("No closing brace found")
        return text[start:end+1]


# ---------------------------
# 2. Data Ingestion
# ---------------------------

def load_fnol_text(path: str) -> str:
    # Check if file is PDF or plain text
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        print(f"Extracting text from {path}...")
        return extract_text_from_pdf(str(p))
    else:
        # Read text file directly
        return p.read_text(encoding="utf-8", errors="ignore")


# ---------------------------
# 3. Specialist Agents
# ---------------------------

def extraction_agent(fnol_text: str) -> Dict:

    prompt = f"""Extract EXACTLY these fields from the FNOL text.
Return STRICT JSON with EXACT key names as shown below.

REQUIRED JSON FORMAT:
{{
  "Policy Information": {{
    "Policy Number": null,
    "Policyholder Name": null,
    "Effective Dates": null
  }},
  "Incident Information": {{
    "Date": null,
    "Time": null,
    "Location": null,
    "Description": null
  }},
  "Involved Parties": {{
    "Claimant": null,
    "Third Parties": null,
    "Contact Details": null
  }},
  "Asset Details": {{
    "Asset Type": null,
    "Asset ID": null,
    "Estimated Damage": null
  }},
  "Other Mandatory Fields": {{
    "Claim Type": null,
    "Attachments": null,
    "Initial Estimate": null
  }}
}}

CRITICAL RULES:
1. Use EXACT key names shown above (including spaces)
2. If a field contains only the label text (like "POLICY NUMBER", "INSURED", "DATE_OF_LOSS") with no actual value filled in, use null
3. Extract only ACTUAL filled-in data values, not form field labels
4. Use null (not empty string) for blank/missing values
5. Return ONLY the JSON object - no markdown, no explanation

FNOL TEXT:
----------------
{fnol_text}
----------------
"""
    raw = run_llm(prompt)
    return json.loads(extract_json(raw))


def normalize_extracted(extracted: Dict) -> Dict:
    """Clean up form labels that LLM extracts as values."""
    form_labels = {
        "policy number", "policy_number", "insured", "date of loss", "time of loss",
        "location of loss", "description of accident", "description of loss",
        "name of claimant", "contact details", "type of asset", "asset_id",
        "estimated damage", "estimate amount", "claim_type", "insurance claim",
        "insured vehicle", "primary e-mail address", "secondary e-mail address",
        "other vehicle / property damaged", "veh", "date of effective",
        "effective start date", "effective end date", "third parties",
        "attachments", "initial estimate", "initial_estimate"
    }

    def clean_value(v):
        if v is None:
            return None
        if isinstance(v, str):
            val = v.strip().lower()
            if val in form_labels or len(val) < 2:
                return None
            if v.strip().isupper() and len(v.strip().split()) <= 3:
                return None
        return v

    for section in extracted:
        if isinstance(extracted[section], dict):
            for key in extracted[section]:
                extracted[section][key] = clean_value(extracted[section][key])

    return extracted


def completeness_agent(extracted: Dict) -> List[str]:
    mandatory = [
        "Policy Number", "Policyholder Name", "Effective Dates",
        "Date", "Time", "Location", "Description",
        "Claimant", "Third Parties", "Contact Details",
        "Asset Type", "Asset ID", "Estimated Damage",
        "Claim Type", "Attachments", "Initial Estimate"
    ]

    # 1. Hybrid Approach: Ask LLM to review completeness
    prompt = (
        f"Review the following extracted fields:\n{json.dumps(extracted, indent=2)}\n"
        f"Are any of these MANDATORY fields missing, empty, or contain placeholders like 'N/A'?\n"
        f"List: {', '.join(mandatory)}\n"
        f"If all are present and valid, answer YES. If any are missing, answer NO."
    )
    # LLM check (can be used for flagging, currently just logging/logic flow)
    _ = run_llm_bool(prompt)
    
    # 2. Python Fallback (Primary source of truth for list return)
    flat = {}
    for section in extracted.values():
        if isinstance(section, dict):
            for k, v in section.items():
                flat[k] = v

    missing = []
    for f in mandatory:
        v = flat.get(f)
        if v is None or (isinstance(v, str) and v.strip() == ""):
            missing.append(f)

    return missing


def investigation_agent(description: str) -> bool:
    # 1. Hybrid Approach: Check LLM first
    if description and len(description) > 10:
        prompt = (
            f"Analyze this insurance claim description for any clear signs of fraud, "
            f"staged accidents, or inconsistent statements. "
            f"Description: \"{description}\"\n"
            f"Is this suspicious? Answer YES or NO."
        )
        result = run_llm_bool(prompt)
        if result is not None:
            return result

    # 2. Fallback: Keyword Analysis
    if not description:
        return False

    text = description.lower()
    for w in ["fraud", "inconsistent", "staged"]:
        if w in text:
            return True
    return False


def injury_agent(extracted: Dict) -> bool:
    claim_type = extracted.get("Other Mandatory Fields", {}).get("Claim Type")
    desc = extracted.get("Incident Information", {}).get("Description")

    # 1. Hybrid Approach: Check LLM first
    if claim_type or desc:
        prompt = (
            f"Based on the following info, does this claim involve BODILY INJURY?\n"
            f"Claim Type: {claim_type}\n"
            f"Description: {desc}\n"
            f"Answer YES or NO."
        )
        result = run_llm_bool(prompt)
        if result is not None:
            return result

    # 2. Fallback: Keyword Analysis
    if not claim_type:
        return False

    return "injury" in str(claim_type).lower()


def fasttrack_agent(extracted: Dict) -> bool:
    # Check if damage is under $25,000 threshold
    dmg = extracted.get("Asset Details", {}).get("Estimated Damage")
    
    # 1. Hybrid Approach: LLM check for value
    if dmg:
        prompt = (
            f"Extract the estimated damage amount from: \"{dmg}\"\n"
            f"Is it clearly LESS THAN $25,000? Answer YES or NO."
        )
        result = run_llm_bool(prompt)
        if result is not None:
            return result

    # 2. Fallback: Deterministic parsing
    if dmg is None:
        return False

    if isinstance(dmg, (int, float)):
        return dmg < 25000

    s = str(dmg)
    nums = re.findall(r"[0-9]+(?:\.[0-9]+)?", s.replace(",", ""))
    if not nums:
        return False

    try:
        val = float(nums[0])
        return val < 25000
    except:
        return False


# ---------------------------
# 4. Coordinator
# ---------------------------

def decide_route(
    extracted: Dict,
    missing: List[str],
    investigation: bool,
    injury: bool,
    fasttrack: bool
):
    if investigation:
        return "Investigation Flag", "Description contains investigation-related keywords."

    if missing:
        return "Manual review", f"Mandatory fields missing: {', '.join(missing)}."

    if injury:
        return "Specialist Queue", "Claim type indicates injury."

    if fasttrack:
        return "Fast-track", "Estimated damage is below 25,000."

    return "Manual review", "No routing rule matched confidently."


# ---------------------------
# 5. Pipeline Entry Point
# ---------------------------

def process_fnol(file_path: str):
    # Main pipeline: extract text → analyze → route
    fnol_text = load_fnol_text(file_path)

    extracted = extraction_agent(fnol_text)
    extracted = normalize_extracted(extracted)

    missing = completeness_agent(extracted)

    description = (
        extracted
        .get("Incident Information", {})
        .get("Description")
    )

    investigation = investigation_agent(description)
    injury = injury_agent(extracted)
    fasttrack = fasttrack_agent(extracted)

    route, reason = decide_route(
        extracted,
        missing,
        investigation,
        injury,
        fasttrack
    )

    final_output = {
        "extractedFields": extracted,
        "missingFields": missing,
        "recommendedRoute": route,
        "reasoning": reason
    }

    return final_output


if __name__ == "__main__":
    import time
    start = time.time()

    # Build path to test PDF in data folder
    pdf_path = os.path.join(os.path.dirname(__file__), "data", "ACORD-Automobile-Loss-Notice-12.05.16.pdf")
    
    if not os.path.exists(pdf_path):
        # Fallback to current dir if data folder usage varies
        pdf_path = "ACORD-Automobile-Loss-Notice-12.05.16.pdf"
        
    result = process_fnol(pdf_path)

    elapsed = time.time() - start

    output_path = "claim_processed_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    print(f"\nCompleted in {elapsed:.2f}s | Output saved to {output_path}")
