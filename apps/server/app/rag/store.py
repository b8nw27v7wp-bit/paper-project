import json
from sqlmodel import Session
from app.models.memory import MemoryChunk
from app.services.memory import embed_text

async def store_chunks(session: Session, user_id: int, chunks: list[str], type_: str = "knowledge", subject: str | None = None) -> list[MemoryChunk]:
    created = []
    for c in chunks:
        if not c.strip():
            continue
        vec = await embed_text(c)
        # subject 拼到 content 前缀以支持按学科检索
        content = f"[{subject}] {c}" if subject else c
        mc = MemoryChunk(user_id=user_id, content=content, embedding=json.dumps(vec), type=type_)
        session.add(mc)
        created.append(mc)
    session.commit()
    for m in created:
        session.refresh(m)
    return created
