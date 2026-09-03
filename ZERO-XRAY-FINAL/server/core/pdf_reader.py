from pathlib import Path
import pymupdf


BASE_DIR = Path(__file__).resolve().parent.parent

PDF_PATH = (
    BASE_DIR
    / "data"
    / "zero_bureaucracy_standards.pdf"
)

TEXT_PATH = (
    BASE_DIR
    / "data"
    / "government_standards.txt"
)

# MERGED FROM P1: an Arabic-language standards text, used as the
# preferred source when the caller explicitly requests lang="ar" and
# the file is present. Purely additive -- when lang is not "ar" or
# this file doesn't exist, behavior is identical to before (PDF
# extraction first, then TEXT_PATH, unchanged).
TEXT_AR_PATH = (
    BASE_DIR
    / "data"
    / "government_standards_ar.txt"
)


def extract_pdf_text():

    if not PDF_PATH.exists():
        return []

    document = pymupdf.open(PDF_PATH)

    pages = []

    try:

        for page_number, page in enumerate(document):

            text = page.get_text(
                "text"
            ).strip()

            pages.append({
                "page": page_number + 1,
                "text": text
            })

    finally:
        document.close()

    return pages


def get_full_standards_text(lang=None):

    # MERGED FROM P1: an explicit lang="ar" request prefers the
    # Arabic-language standards text file when present, ahead of the
    # PDF/TEXT_PATH priority below. Optional and additive -- omitting
    # lang (the default) preserves P2's existing PDF-first behavior
    # unchanged.
    if lang == "ar" and TEXT_AR_PATH.exists():
        text = TEXT_AR_PATH.read_text(encoding="utf-8").strip()
        if text:
            print(
                f"Government standards loaded ({len(text)} chars) "
                f"from {TEXT_AR_PATH.name}."
            )
            return text

    # First try the original PDF
    pages = extract_pdf_text()

    pdf_text = "\n\n".join(
        f"[PAGE {page['page']}]\n{page['text']}"
        for page in pages
        if page["text"]
    ).strip()

    if pdf_text:
        print(
            "Government standards loaded "
            "directly from PDF."
        )

        return pdf_text

    # Scanned PDF fallback
    if TEXT_PATH.exists():

        text = TEXT_PATH.read_text(
            encoding="utf-8"
        ).strip()

        if text:

            print(
                "Scanned PDF detected."
            )

            print(
                "Government standards loaded "
                "from extracted text."
            )

            return text

    raise ValueError(
        "Government standards could not be loaded. "
        "The PDF is scanned and "
        "government_standards.txt is empty or missing."
    )
