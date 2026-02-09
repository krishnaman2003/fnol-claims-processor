# FNOL Claims Processing - Local LLM Implementation

A First Notice of Loss (FNOL) claims processing system using local LLM (llama.cpp) for intelligent field extraction and automated routing.

## Features

- **100% Offline** - No API keys, no internet required after setup
- **Fast PDF Processing** - PyMuPDF direct text extraction (0.1s vs 30s+ with OCR)
- **Local LLM Reasoning** - Qwen 2.5 1.5B model for accurate field extraction
- **Intelligent Routing** - Automatic claim classification: Fast-track, Manual Review, Investigation Flag, Specialist Queue
- **Lightweight** - Only 2 Python dependencies (llama-cpp-python + PyMuPDF)

---

## File Structure

```
src/
├── main.py              # Entry point - orchestrates extraction and routing
├── ingestion.py         # PDF text extraction pipeline
├── pdf_extraction.py    # PyMuPDF wrapper (fast text extraction)
├── data/                # Input PDFs go here
│   └── ACORD-Automobile-Loss-Notice-12.05.16.pdf
├── model/               # Local LLM model (GGUF format)
│   └── qwen2.5-1.5b-instruct-q4_k_m.gguf
├── claim_processed_output.json  # Generated output
└── requirements.txt     # Python dependencies
```

---

## Prerequisites

### 1. Python 3.8+ installed

Check your Python version:
```bash
python --version
```

### 2. Install Python Dependencies

```bash
cd src
pip install llama-cpp-python PyMuPDF
```

**Note**: On Windows, `llama-cpp-python` may require Visual C++ Build Tools. If installation fails:

```bash
# Alternative: Install pre-built wheel
pip install llama-cpp-python --prefer-binary
```

---

## Step 1: Download the LLM Model

The system requires a GGUF format model file.

### Option A: Download Qwen 2.5 1.5B Instruct (Recommended)

1. **Create the model directory:**
```bash
mkdir model
cd model
```

2. **Download from HuggingFace:**

Visit: https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF

Download: `qwen2.5-1.5b-instruct-q4_k_m.gguf` (~1.1 GB)

3. **Place in `src/model/` directory:**
```
src/
└── model/
    └── qwen2.5-1.5b-instruct-q4_k_m.gguf
```

### Option B: Download via Command Line (requires huggingface-cli)

```bash
# Install HuggingFace CLI
pip install huggingface-hub

# Download model
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir ./model --local-dir-use-symlinks False
```

---

## Step 2: Prepare Input PDF

Place your FNOL PDF in the `data/` directory:

```bash
# Copy your PDF to the data folder
cp your-claim.pdf src/data/
```

**Supported formats:** Any text-based PDF (ACORD forms, claim reports, etc.)

**Test file included:** `ACORD-Automobile-Loss-Notice-12.05.16.pdf` (blank ACORD template for testing)

---

## Step 3: Run the Pipeline

### Basic Execution

```bash
cd src
python main.py
```

### Expected Output

```
Extracting text from D:\project\assignment\src\data\ACORD-Automobile-Loss-Notice-12.05.16.pdf...
{
  "extractedFields": {
    "Policy Information": {
      "Policy Number": null,
      "Policyholder Name": null,
      "Effective Dates": null
    },
    "Incident Information": {
      "Date": null,
      "Time": null,
      "Location": null,
      "Description": null
    },
    "Involved Parties": {
      "Claimant": null,
      "Third Parties": null,
      "Contact Details": null
    },
    "Asset Details": {
      "Asset Type": null,
      "Asset ID": null,
      "Estimated Damage": null
    },
    "Other Mandatory Fields": {
      "Claim Type": null,
      "Attachments": null,
      "Initial Estimate": null
    }
  },
  "missingFields": ["Policy Number", "Policyholder Name", ...],
  "recommendedRoute": "Manual review",
  "reasoning": "Mandatory fields missing: ..."
}

Completed in 115.42s | Output saved to claim_processed_output.json
```

**Output file:** `claim_processed_output.json` - Structured JSON with extracted fields and routing decision.

---

## How It Works

### Pipeline Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│  PDF Input  │────▶│  PyMuPDF    │────▶│  Local LLM      │────▶│  JSON Output │
│  (data/)    │     │  (extract)  │     │  (reasoning)    │     │  (routing)   │
└─────────────┘     └─────────────┘     └─────────────────┘     └──────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
            ┌──────────────┐      ┌─────────────────┐      ┌──────────────┐
            │ Extraction   │      │ Completeness    │      │ Routing      │
            │ Agent        │      │ Agent           │      │ Decision     │
            │ (LLM call)   │      │ (code logic)    │      │ (rules)      │
            └──────────────┘      └─────────────────┘      └──────────────┘
```

### Specialist Agents

| Agent | Function | Implementation |
|-------|----------|----------------|
| **Extraction Agent** | Extracts 16 mandatory fields from PDF text | LLM prompt with strict JSON schema |
| **Completeness Agent** | Checks for missing/null fields | Python code (no LLM) |
| **Investigation Agent** | Detects fraud keywords | Python string matching |
| **Injury Agent** | Detects injury claim types | Python string matching |
| **Fast-track Agent** | Checks damage threshold (<$25K) | Python number parsing |

### Routing Rules (Priority Order)

1. **Investigation Flag** - Keywords: "fraud", "inconsistent", "staged" in description
2. **Manual Review** - Any mandatory field is missing
3. **Specialist Queue** - Claim type contains "injury"
4. **Fast-track** - Estimated damage < $25,000 AND all fields present
5. **Manual Review** (default) - No rules matched

### Post-Processing

The `normalize_extracted()` function filters out form labels (e.g., "POLICY NUMBER", "INSURED") that the LLM might extract as values when processing blank templates. Only actual filled-in data is retained.

---

## Customization

### Change Input PDF

Edit `main.py` line 283:

```python
pdf_path = os.path.join(os.path.dirname(__file__), "data", "your-pdf-name.pdf")
```

### Adjust LLM Parameters

In `main.py` lines 14-20:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `n_ctx` | 4096 | Context window (reduce if OOM) |
| `n_threads` | 8 | CPU threads (match your cores) |
| `temperature` | 0 | 0=deterministic, higher=more creative |
| `max_tokens` | 800 | Output length limit |

### Add Custom Routing Rules

Edit the `decide_route()` function in `main.py` lines 196-216:

```python
def decide_route(extracted, missing, investigation, injury, fasttrack):
    if investigation:
        return "Investigation Flag", "..."
    # Add your custom rule here
    if your_custom_condition:
        return "Custom Queue", "Your reasoning"
    # ... existing rules
```

---

## Troubleshooting

### Issue: "Model file not found"

**Error:**
```
Error loading model: unable to open model file
```

**Fix:**
1. Ensure model file is in `src/model/qwen2.5-1.5b-instruct-q4_k_m.gguf`
2. Check file path in `main.py` line 15 matches your filename

### Issue: "llama_cpp not found"

**Error:**
```
ModuleNotFoundError: No module named 'llama_cpp'
```

**Fix:**
```bash
pip install llama-cpp-python
```

### Issue: Slow inference

**Causes:**
- CPU-only mode (no GPU acceleration)
- Large context window (reduce `n_ctx` to 2048)
- Too many threads (set `n_threads` to physical core count)

**Fix:**
```python
# Reduce context window
n_ctx=2048,  # Was 4096

# Match CPU cores
n_threads=4,  # Adjust to your CPU
```

### Issue: JSON parsing errors

**Cause:** LLM outputting markdown or extra text

**Fix:** Already handled by `extract_json()` function in `main.py` lines 223-238. If issues persist, check the LLM temperature is 0.

### Issue: Blank template returns labels as values

**Cause:** PDF has no filled data, only form field labels

**Fix:** Already handled by `normalize_extracted()` post-processing. Ensure your PDF has actual filled-in values.

---

## Performance Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| PDF text extraction | ~0.1s | PyMuPDF direct text |
| LLM loading (first run) | ~5-10s | One-time per session |
| LLM extraction + routing | ~100-120s | Single 1.5B model call |
| **Total pipeline** | **~110-130s** | End-to-end |

**Comparison with cloud API version:**
- 10x faster PDF extraction (0.1s vs 10s with OCR)
- 5-10x slower LLM (local CPU vs cloud GPU)
- **Trade-off:** Privacy + no API costs vs speed

---

## Advanced: Model Quantization Options

Smaller models = faster inference, slightly lower accuracy.

| Model | Size | Speed | Use Case |
|-------|------|-------|----------|
| `qwen2.5-1.5b-instruct-q4_k_m.gguf` | ~1.1 GB | Baseline | Balanced |
| `qwen2.5-0.5b-instruct-q4_k_m.gguf` | ~400 MB | 2x faster | Quick tests |
| `qwen2.5-3b-instruct-q4_k_m.gguf` | ~2 GB | 0.5x speed | Higher accuracy |

Download from: https://huggingface.co/Qwen

---

## License

- **PyMuPDF**: AGPL/commercial
- **llama-cpp-python**: MIT
- **Qwen models**: Apache 2.0 (check HuggingFace for specific terms)

---

## Next Steps

1. ✅ Download model (Step 1)
2. ✅ Install dependencies (Prerequisites)
3. ✅ Prepare PDF (Step 2)
4. ✅ Run pipeline (Step 3)
5. ✅ Check `claim_processed_output.json` for results

For questions or issues, check the code comments in `main.py` for detailed logic explanations.
