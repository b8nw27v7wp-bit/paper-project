"""Pi-ai 启示的统一LLM - provider无关 (deepseek/qwen/anthropic/openai)"""
from typing import Any

from app.core.config import get_settings

settings = get_settings()

PROVIDER_MAP = {
    "zhipu": {"base": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.7-flash"},
    "deepseek": {"base": "https://api.deepseek.com", "model": "deepseek-chat"},
    "qwen": {"base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "openai": {"base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "anthropic": {"base": None, "model": "claude-3-5-sonnet"},
}

class UnifiedClient:
    def __init__(self, provider: str | None = None):
        if provider:
            self.provider = provider
        elif "bigmodel.cn" in settings.llm_base_url:
            self.provider = "zhipu"
        elif "deepseek" in settings.llm_base_url:
            self.provider = "deepseek"
        else:
            self.provider = "openai"
        self.cfg = PROVIDER_MAP.get(self.provider, PROVIDER_MAP["openai"])

    async def chat(self, messages: list[dict[str, Any]], **kw) -> str:
        # BYOK - 用统一入参，底层仍走 openai SDK 兼容
        try:
            from openai import AsyncOpenAI
            base = self.cfg["base"] or settings.llm_base_url
            model = kw.pop("model", self.cfg["model"])
            client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=base)
            resp = await client.chat.completions.create(model=model, messages=messages, **kw)
            return resp.choices[0].message.content or ""
        except Exception as e:
            raise e

    async def embed(self, text: str, dim: int = 1536) -> list[float]:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
            resp = await client.embeddings.create(model="text-embedding-3-small", input=text)
            vec = resp.data[0].embedding
            if len(vec) != dim:
                vec = (vec[:dim] + [0.0]*dim)[:dim]
            import math
            n = math.sqrt(sum(x*x for x in vec))
            return [x/n for x in vec] if n else vec
        except Exception:
            # 语义化 hash mock 回退（与 memory._hash_mock_embedding 一致）
            import hashlib
            import math
            vals = [0.0] * dim
            if text:
                for i, ch in enumerate(text):
                    h = hashlib.sha256(ch.encode()).digest()
                    idx = int.from_bytes(h[:4], "little") % dim
                    vals[idx] += 1.0
                    if i < len(text) - 1:
                        big = text[i : i + 2]
                        h2 = hashlib.sha256(big.encode()).digest()
                        idx2 = int.from_bytes(h2[:4], "little") % dim
                        vals[idx2] += 0.5
            n = math.sqrt(sum(x * x for x in vals))
            return [x / n for x in vals] if n and n > 0 else vals
