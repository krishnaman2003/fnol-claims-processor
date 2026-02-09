import os                    # For file path operations
import json                  # For parsing LLM output
import re                     # For extracting numbers from damage amounts
from ingestion import extract_text_from_pdf  # PDF text extraction module
from pathlib import Path      # Cross-platform file paths
from typing import Dict, List  # Type hints for clarity

from llama_cpp import Llama   # Local LLM engine (llama.cpp)

# ---------------------------
# 1. Lightweight LLM (llama.cpp)
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
    # Send prompt to local LLM with system instruction
    out = llm(
        f"<|system|>You are a precise information extraction and reasoning engine.\n"
        f"<|user|>{prompt}\n<|assistant|>",
        max_tokens=800,          # Limit response length
        stop=["<|user|>"]         # Stop at user token
    )
    return out["choices"][0]["text"].strip()


# ---------------------------
# 2. Load FNOL document
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
# 3. Specialist agents
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
    # Common form field labels to filter out
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
        # Keep null as null
        if v is None:
            return None
        # Check if string value is just a label
        if isinstance(v, str):
            val = v.strip().lower()
            # Reject if it matches a label or is too short
            if val in form_labels or len(val) < 2:
                return None
            # Reject if all uppercase (likely a label)
            if v.strip().isupper() and len(v.strip().split()) <= 3:
                return None
        return v

    # Clean each field in each section
    for section in extracted:
        if isinstance(extracted[section], dict):
            for key in extracted[section]:
                extracted[section][key] = clean_value(extracted[section][key])

    return extracted


def completeness_agent(extracted: Dict) -> List[str]:
    # All 16 fields that must be present for complete claim
    mandatory = [
        "Policy Number", "Policyholder Name", "Effective Dates",
        "Date", "Time", "Location", "Description",
        "Claimant", "Third Parties", "Contact Details",
        "Asset Type", "Asset ID", "Estimated Damage",
        "Claim Type", "Attachments", "Initial Estimate"
    ]

    # Flatten nested dict to check all fields
    flat = {}
    for section in extracted.values():
        if isinstance(section, dict):
            for k, v in section.items():
                flat[k] = v

    # Find fields that are null or empty
    missing = []
    for f in mandatory:
        v = flat.get(f)
        if v is None or (isinstance(v, str) and v.strip() == ""):
            missing.append(f)

    return missing


def investigation_agent(description: str) -> bool:
    # Check for fraud keywords in description
    if not description:
        return False

    text = description.lower()
    for w in ["fraud", "inconsistent", "staged"]:
        if w in text:
            return True
    return False


def injury_agent(extracted: Dict) -> bool:
    # Check if claim type indicates injury
    claim_type = (
        extracted
        .get("Other Mandatory Fields", {})
        .get("Claim Type")
    )

    if not claim_type:
        return False

    return "injury" in str(claim_type).lower()


def fasttrack_agent(extracted: Dict) -> bool:
    # Check if damage is under $25,000 threshold
    dmg = (
        extracted
        .get("Asset Details", {})
        .get("Estimated Damage")
    )

    if dmg is None:
        return False

    # Direct number comparison
    if isinstance(dmg, (int, float)):
        return dmg < 25000

    # Extract number from string (handles "$5,000" or "5000 USD")
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
# 5. Deterministic coordinator
# ---------------------------

def decide_route(
    extracted: Dict,
    missing: List[str],
    investigation: bool,
    injury: bool,
    fasttrack: bool
):
    # Priority order: Investigation > Missing > Injury > Fast-track

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
# 6. Small helper
# ---------------------------

def extract_json(text: str) -> str:
    # Find JSON object in LLM output (handles markdown wrappers)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON found in LLM output")

    try:
        # Try strict JSON parsing first
        obj, _ = json.JSONDecoder().raw_decode(text, start)
        return json.dumps(obj)
    except Exception as e:
        # Fallback: slice between first { and last }
        end = text.rfind("}")
        if end == -1:
             raise ValueError("No closing brace found")
        return text[start:end+1]

# ---------------------------
# 7. Main pipeline
# ---------------------------

def process_fnol(file_path: str):
    # Main pipeline: extract text → analyze → route

    fnol_text = load_fnol_text(file_path)

    extracted = extraction_agent(fnol_text)
    extracted = normalize_extracted(extracted)  # Filter out labels

    missing = completeness_agent(extracted)

    # Get description for investigation check
    description = (
        extracted
        .get("Incident Information", {})
        .get("Description")
    )

    # Run all specialist agents
    investigation = investigation_agent(description)
    injury = injury_agent(extracted)
    fasttrack = fasttrack_agent(extracted)

    # Get final routing decision
    route, reason = decide_route(
        extracted,
        missing,
        investigation,
        injury,
        fasttrack
    )

    # Build output structure
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
    result = process_fnol(pdf_path)

    elapsed = time.time() - start

    # Save to JSON file
    output_path = "claim_processed_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    # Print results
    print(json.dumps(result, indent=2))
    print(f"\nCompleted in {elapsed:.2f}s | Output saved to {output_path}")
