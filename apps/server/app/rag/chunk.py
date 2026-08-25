import re


def chunk_text(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    if not text:
        return []
    text = text.strip()
    if not text:
        return []
    # 按段落分割：优先双换行，其次单换行；保留段落语义
    # 若含段落分隔符则按段落切，否则整体按滑动窗口切
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    # 若只有一段且包含单换行且每段较短，尝试按单换行再细拆
    if len(paragraphs) == 1 and "\n" in text:
        maybe = [p.strip() for p in text.split("\n") if p.strip()]
        # 仅当拆后段落数>1且平均长度较小 (< size*0.8) 时采用
        if len(maybe) > 1 and sum(len(p) for p in maybe) / len(maybe) < size * 0.8:
            paragraphs = maybe
    chunks: list[str] = []
    for para in paragraphs:
        # 段落内按大小+overlap滑动切
        if len(para) <= size:
            chunks.append(para)
        else:
            start = 0
            n = len(para)
            while start < n:
                end = min(start + size, n)
                # 尽量不在中间截断词（中文按字符，无需额外逻辑）
                chunk = para[start:end].strip()
                if chunk:
                    chunks.append(chunk)
                if end >= n:
                    break
                start = end - overlap
                # 防止死循环：overlap 必须 < size
                if overlap >= size:
                    start = end
    # 若段落切分后仍为空（极端情况），兜底整体滑窗
    if not chunks:
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
        import io

        from pypdf import PdfReader
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
