from pdf_extraction import extract_text_from_pdf as extract_pdf_text  # Fast PyMuPDF extraction

def extract_text_from_pdf(filepath: str) -> str:
    """Fast text extraction from PDF. Returns plain text (not JSON) for direct LLM processing."""
    print(f"Extracting text from {filepath}...")  # Log extraction start
    return extract_pdf_text(filepath)  # Call extraction function
