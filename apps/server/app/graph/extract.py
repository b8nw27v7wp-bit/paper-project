import re
from typing import List, Tuple

# 简单三元组抽取：匹配 “A 是 B 的前置” “A -> B” “A 依赖 B”
PATTERNS = [
    re.compile(r"(\w+)\s*是\s*(\w+)\s*的前置"),
    re.compile(r"(\w+)\s*->\s*(\w+)"),
    re.compile(r"(\w+)\s*依赖\s*(\w+)"),
]

def mock_extract_triples(text: str) -> List[Tuple[str, str, str]]:
    triples = []
    for pat in PATTERNS:
        for m in pat.finditer(text):
            triples.append((m.group(1).strip(), "PREREQUISITE", m.group(2).strip()))
    # 兜底：按句切，取首两名词
    if not triples:
        # 简单按标点切，取长度>1的词
        sents = re.split(r"[。；;,.，\n]", text)
        for s in sents[:5]:
            words = [w for w in re.split(r"\s+", s.strip()) if len(w) >= 2]
            if len(words) >= 2:
                triples.append((words[0], "PREREQUISITE", words[1]))
                if len(triples) >= 3:
                    break
    # 去重
    seen = set()
    uniq = []
    for t in triples:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq[:10]

async def llm_extract_triples(text: str) -> List[Tuple[str, str, str]]:
    # 若有Key则调LLM，否则mock
    from app.core.config import get_settings
    s = get_settings()
    if not s.llm_api_key:
        return mock_extract_triples(text)
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)
        prompt = f"从文本抽取知识点三元组 (Knowledge)-[PREREQUISITE]->(Knowledge)，输出JSON数组 [{{\"from\":\"A\",\"to\":\"B\"}}]，最多5条。文本:{text[:2000]}"
        resp = await client.chat.completions.create(model=s.llm_model, messages=[{"role":"user","content":prompt}], temperature=0.3, timeout=15)
        import json
        txt = resp.choices[0].message.content or ""
        start = txt.find("["); end = txt.rfind("]")+1
        if start>=0 and end>start:
            arr = json.loads(txt[start:end])
            return [(x["from"], "PREREQUISITE", x["to"]) for x in arr if "from" in x and "to" in x]
    except Exception:
        pass
    return mock_extract_triples(text)
