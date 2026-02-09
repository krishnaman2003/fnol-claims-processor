import fitz  # PyMuPDF - fast PDF text extraction

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from all pages of a PDF file."""
    text_parts = []
    try:
        doc = fitz.open(pdf_path)          # Open PDF file
        for page in doc:                    # Loop through each page
            text_parts.append(page.get_text())  # Extract text from page
        doc.close()                         # Close PDF to free memory
        return "\n".join(text_parts)        # Join all pages with newlines
    except Exception as e:
        print(f"Error extracting PDF: {e}")
        return ""
