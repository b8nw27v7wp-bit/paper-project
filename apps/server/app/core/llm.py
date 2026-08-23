"""Pi-ai 启示的统一LLM - provider无关 (deepseek/qwen/anthropic/openai)"""
from typing import List, Dict, Any
from app.core.config import get_settings

settings = get_settings()

PROVIDER_MAP = {
    "deepseek": {"base": "https://api.deepseek.com", "model": "deepseek-chat"},
    "qwen": {"base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "openai": {"base": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "anthropic": {"base": None, "model": "claude-3-5-sonnet"},
}

class UnifiedClient:
    def __init__(self, provider: str | None = None):
        self.provider = provider or ("deepseek" if "deepseek" in settings.llm_base_url else "openai")
        self.cfg = PROVIDER_MAP.get(self.provider, PROVIDER_MAP["openai"])

    async def chat(self, messages: List[Dict[str, Any]], **kw) -> str:
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

    async def embed(self, text: str, dim: int = 1536) -> List[float]:
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
            # hash mock 回退
            import hashlib, math
            h = hashlib.sha256(text.encode()).digest()
            vals = [((h[i % len(h)]/255)*2-1) for i in range(dim)]
            n = math.sqrt(sum(x*x for x in vals))
            return [x/n for x in vals] if n else vals
