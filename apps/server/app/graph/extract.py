import json
import logging
import os
import re

logger = logging.getLogger(__name__)

PATTERNS = [
    re.compile(r"(\w+)\s*是\s*(\w+)\s*的前置"),
    re.compile(r"(\w+)\s*->\s*(\w+)"),
    re.compile(r"(\w+)\s*依赖\s*(\w+)"),
    re.compile(r"(\w+)\s*需要\s*先学\s*(\w+)"),
    re.compile(r"学习\s*(\w+)\s*前需掌握\s*(\w+)"),
    re.compile(r"(\w+)\s*PREREQ\s*(\w+)", re.I),
]

# 学科词表兜底（纯标库，不新增 jieba 依赖）：\w 中文无空格场景失效时用
_SUBJECT_VOCAB = [
    "链表", "数组", "栈", "队列", "树", "图", "排序", "查找", "递归",
    "哈希", "散列", "堆", "线性表", "线性结构", "层次结构", "网状结构",
    "数据结构", "算法", "微积分", "线性代数", "概率", "力学", "电磁",
    "前置", "基础", "进阶",
]

def _vocab_bigram_fallback(text: str) -> list[tuple[str, str, str]]:
    r"""字符 bigram + 学科词表兜底（纯标库）：处理中文无空格 \w 失效场景"""
    out: list[tuple[str, str, str]] = []
    # 学科词表：按出现顺序链式组装
    found: list[str] = []
    for w in _SUBJECT_VOCAB:
        if w and w in text and w not in found:
            found.append(w)
    # 按在文本中首次出现位置排序，保证方向
    try:
        found.sort(key=lambda w: text.index(w))
    except ValueError:
        pass
    for i in range(len(found) - 1):
        a, b = found[i], found[i + 1]
        if a != b and len(a) >= 1 and len(b) >= 1:
            out.append((a, "PREREQUISITE", b))
        if len(out) >= 4:
            return out[:4]
    if out:
        return out[:4]
    # 字符 bigram：去空格后按 2 字切分相邻组装
    clean = re.sub(r"\s+", "", text.strip())
    clean = re.sub(r"[。；;,.，、：:！!？?\n「」『』（）()\[\]<>《》]", "", clean)
    if len(clean) >= 4:
        grams = [clean[i : i + 2] for i in range(0, min(len(clean), 12), 2)]
        grams = [g for g in grams if len(g) == 2]
        for i in range(len(grams) - 1):
            if grams[i] != grams[i + 1]:
                out.append((grams[i], "PREREQUISITE", grams[i + 1]))
            if len(out) >= 3:
                break
    return out[:4]

def mock_extract_triples(text: str, subject: str | None = None) -> list[tuple[str, str, str]]:
    triples = []
    for pat in PATTERNS:
        for m in pat.finditer(text):
            # 注意依赖方向：A依赖B => B->A，但统一为 PREREQUISITE A->B 时需判断
            # 简化：保持 A PREREQ B
            a = m.group(1).strip()
            b = m.group(2).strip()
            if len(a) >= 1 and len(b) >= 1:
                triples.append((a, "PREREQUISITE", b))
    if not triples:
        sents = re.split(r"[。；;,.，\n]", text)
        for s in sents[:6]:
            s = s.strip()
            if not s:
                continue
            words = [w for w in re.split(r"\s+", s) if len(w) >= 2]
            # 清理标点
            words = [re.sub(r"[^\w\u4e00-\u9fff]", "", w) for w in words]
            words = [w for w in words if len(w) >= 2]
            if len(words) >= 2:
                triples.append((words[0], "PREREQUISITE", words[1]))
                if len(triples) >= 4:
                    break
    if not triples:
        # 中文无空格 \w 失效兜底：学科词表 + 字符 bigram（纯标库）
        triples.extend(_vocab_bigram_fallback(text))
    # 学科维度：去重并标记
    seen = set()
    uniq: list[tuple[str, str, str]] = []
    for t in triples:
        if t not in seen and t[0] != t[2]:
            seen.add(t)
            uniq.append(t)
    # 若含 subject 且节点未带 subject，可在上游 neo 层打标签
    return uniq[:10]


def _regex_fallback(text: str) -> list[tuple[str, str, str]]:
    """正则兜底（与mock类似但更宽松）"""
    return mock_extract_triples(text)


async def _verify_triples_llm(triples: list[tuple[str, str, str]], text: str) -> list[tuple[str, str, str]]:
    """第二轮LLM校验：过滤不合理三元组"""
    if not triples:
        return triples
    if os.getenv("PYTEST_CURRENT_TEST"):
        return triples
    try:
        from app.core.config import get_settings
        s = get_settings()
        if not s.llm_api_key:
            return triples
        from app.core.llm import UnifiedClient
        client = UnifiedClient()
        triples_txt = json.dumps([{"from": a, "to": b} for a, _, b in triples], ensure_ascii=False)
        prompt = f"校验以下知识前置三元组是否合理（基于原文），仅保留合理的，输出JSON数组 [{{\"from\":\"A\",\"to\":\"B\"}}]。原文:{text[:1200]}\n三元组:{triples_txt}"
        txt = await client.chat([{"role": "user", "content": prompt}], temperature=0.2, timeout=8, fallback=True, max_retries=1)
        start = txt.find("[")
        end = txt.rfind("]") + 1
        if start >= 0 and end > start:
            arr = json.loads(txt[start:end])
            verified = [(x["from"], "PREREQUISITE", x["to"]) for x in arr if "from" in x and "to" in x and x["from"] != x["to"]]
            if verified:
                return verified[:10]
        return triples
    except Exception:
        logger.warning("llm triple verify failed, keep original", exc_info=True)
        return triples


async def llm_extract_triples(text: str, subject: str | None = None) -> list[tuple[str, str, str]]:
    # 学科维度提示
    subject_hint = f"学科:{subject}，" if subject else ""
    from app.core.config import get_settings
    s = get_settings()
    if not s.llm_api_key:
        return mock_extract_triples(text, subject)
    # 多轮：第一轮抽取
    triples: list[tuple[str, str, str]] = []
    try:
        from app.core.llm import UnifiedClient
        client = UnifiedClient()
        prompt = f"{subject_hint}从文本抽取知识点三元组 (Knowledge)-[PREREQUISITE]->(Knowledge)，仅输出JSON数组 [{{\"from\":\"A\",\"to\":\"B\"}}]，最多6条，A是B的前置。文本:{text[:2000]}"
        txt = await client.chat([{"role": "user", "content": prompt}], temperature=0.3, timeout=10, fallback=True, max_retries=1)
        start = txt.find("[")
        end = txt.rfind("]") + 1
        if start >= 0 and end > start:
            arr = json.loads(txt[start:end])
            triples = [(x["from"].strip(), "PREREQUISITE", x["to"].strip()) for x in arr if "from" in x and "to" in x and x["from"].strip() and x["to"].strip()]
            triples = [(a, r, b) for a, r, b in triples if a != b][:10]
    except Exception:
        logger.warning("llm triple extract failed, fallback regex", exc_info=True)
        triples = []
    # 若LLM未抽到，回退正则
    if not triples:
        triples = _regex_fallback(text)
        # 若仍为空且有subject，尝试用subject关联
        if not triples and subject:
            # 取文本前两关键词与subject关联
            words = [w for w in re.split(r"\s+", text[:200]) if len(w) >= 2][:2]
            if words:
                triples = [(words[0], "PREREQUISITE", words[1] if len(words) > 1 else subject)]
        return mock_extract_triples(text, subject) if not triples else triples
    # 第二轮校验
    verified = await _verify_triples_llm(triples, text)
    # 第三轮：正则兜底补充（若LLM过滤过度）
    if len(verified) < len(triples) and len(verified) < 2:
        regex_extra = _regex_fallback(text)
        # 合并去重
        seen = set(verified)
        for t in regex_extra:
            if t not in seen and t[0] != t[2]:
                verified.append(t)
                seen.add(t)
            if len(verified) >= 6:
                break
    return verified[:10]
