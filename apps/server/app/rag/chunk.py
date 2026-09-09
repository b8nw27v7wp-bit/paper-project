import re


def chunk_text(text: str, size: int = 512, overlap: int = 50) -> list[str]:
    # 参数归一：防越界/死循环（size<=0 或 overlap 越界时钳制）
    try:
        size = int(size)
    except Exception:
        size = 512
    try:
        overlap = int(overlap)
    except Exception:
        overlap = 50
    if size <= 0:
        size = 512
    if overlap < 0:
        overlap = 0
    if overlap >= size:
        overlap = size - 1 if size > 1 else 0
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
            piece = text[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= n:
                break
            start = end - overlap
            if overlap >= size:
                start = end
    return chunks

def decode_bytes_smart(file_bytes: bytes) -> str:
    """智能解码：优先 utf-8 / utf-8-sig，失败回退 gbk/gb18030，最后 replace 兜底，避免中文乱码"""
    if not file_bytes:
        return ""
    # 去除 BOM
    if file_bytes.startswith(b"\xef\xbb\xbf"):
        try:
            return file_bytes[3:].decode("utf-8")
        except Exception:
            pass
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            text = file_bytes.decode(enc)
            # 启发式：若 utf-8 解出大量 � 则视为误判，继续尝试 gbk
            if enc.startswith("utf-8") and "\ufffd" in text and len(text) > 20:
                continue
            return text
        except Exception:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        import io

        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        texts = []
        for p in reader.pages:
            t = p.extract_text() or ""
            texts.append(t)
        joined = "\n".join(texts)
        if joined.strip():
            return joined
        # PDF 无文本则回退智能解码
        return decode_bytes_smart(file_bytes)
    except Exception:
        return decode_bytes_smart(file_bytes)

def extract_image_text(file_bytes: bytes) -> str:
    # P2才接Qwen-VL，此处mock返回空，由上游决定OCR
    return ""
