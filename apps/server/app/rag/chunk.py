def chunk_text(text: str, size: int = 512, overlap: int = 50) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = end - overlap
    return chunks

def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(file_bytes))
        texts = []
        for p in reader.pages:
            t = p.extract_text() or ""
            texts.append(t)
        return "\n".join(texts)
    except Exception:
        # fallback: try utf-8
        try:
            return file_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return ""

def extract_image_text(file_bytes: bytes) -> str:
    # P2才接Qwen-VL，此处mock返回空，由上游决定OCR
    return ""
