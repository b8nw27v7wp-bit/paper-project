"""Pi-ai 启示的统一LLM - provider无关 (deepseek/qwen/anthropic/openai)

参考 Pi/packages/ai/src/models.ts:254-733 ModelsImpl + Pi/packages/ai/src/providers/all.ts:53-132
实现 provider 无关分发、fallback 链、重试与超时隔离。
"""
import asyncio
import hashlib
import math
import os
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

# 默认 fallback 顺序（对标 Pi 的 defaultModelPerProvider 优先级）
FALLBACK_ORDER = ["zhipu", "deepseek", "qwen", "openai"]

_PROVIDER_ENV_MAP = {
    "zhipu": ["ZHIPU_API_KEY", "BIGMODEL_API_KEY", "ZHIPU_API_KEY_ENV"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "qwen": ["QWEN_API_KEY", "DASHSCOPE_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
}

# S3: 配额/账单类永不重试（优先判否）
# Pi对标(ai/src/utils/retry.ts)：配额/账单类优先判否，补齐网关常见措辞
NON_RETRYABLE = ("insufficient_quota", "billing", "GoUsageLimit", "FreeUsageLimit", "quota exceeded", "out of budget", "Monthly usage limit", "available balance", "account_deactivated")


def _get_api_key_for_provider(provider: str) -> str:
    # 无专属 env key 直接返回空（不复用 settings.llm_api_key，避免跨 provider 401 连锁 fallback）
    for env in _PROVIDER_ENV_MAP.get(provider, []):
        v = os.getenv(env)
        if v:
            return v
    return ""


def _get_base_for_provider(provider: str) -> str | None:
    cfg = PROVIDER_MAP.get(provider)
    if cfg and cfg.get("base"):
        return cfg["base"]
    # anthropic 类无 openai 兼容 base，返回全局 base 供上层决定是否跳过
    return settings.llm_base_url


def _is_retryable(err: Exception) -> bool:
    msg = str(err).lower()
    # S3: NON_RETRYABLE 优先判否（含 401 且命中配额类直接 False）
    for _nr in NON_RETRYABLE:
        try:
            if str(_nr).lower() in msg:
                return False
        except Exception:
            continue
    # status_code 401 且 msg 命中配额类直接 False（已在上一步覆盖，此处显式兜底 401 永不重试）
    try:
        _sc = getattr(err, "status_code", None)
        if _sc is None:
            _sc = getattr(err, "status", None)
        if _sc is None:
            _sc = getattr(err, "code", None)
        if _sc is None:
            _resp = getattr(err, "response", None)
            if _resp is not None:
                _sc = getattr(_resp, "status_code", None)
        _sc_int: int | None = None
        if isinstance(_sc, int) and not isinstance(_sc, bool):
            _sc_int = _sc
        elif isinstance(_sc, str) and _sc.isdigit():
            _sc_int = int(_sc)
        if _sc_int == 401:
            return False
    except Exception:
        pass
    # 超时/限流可重试
    if "timeout" in msg or "timed out" in msg or "429" in msg or "rate limit" in msg or "overloaded" in msg:
        return True
    # openai SDK 的 status_code
    for attr in ("status_code", "status", "code"):
        v = getattr(err, attr, None)
        if isinstance(v, int) and 500 <= v < 600:
            return True
        if isinstance(v, str) and v.isdigit() and 500 <= int(v) < 600:
            return True
    # httpx / openai APIStatusError 的 response
    resp = getattr(err, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if isinstance(sc, int) and (sc == 429 or 500 <= sc < 600):
            return True
    if "502" in msg or "503" in msg or "504" in msg:
        return True
    return False


def _hash_mock_embedding(text: str, dim: int = 1536) -> list[float]:
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


class UnifiedClient:
    def __init__(self, provider: str | None = None):
        base_url = settings.llm_base_url or ""
        if provider:
            self.provider = provider
        elif "bigmodel.cn" in base_url:
            self.provider = "zhipu"
        elif "deepseek" in base_url:
            self.provider = "deepseek"
        else:
            self.provider = "openai"
        self.cfg = PROVIDER_MAP.get(self.provider, PROVIDER_MAP["openai"])

    def _build_fallback_chain(self, fallback: bool) -> list[str]:
        if not fallback:
            return [self.provider]
        chain = [self.provider]
        for p in FALLBACK_ORDER:
            if p not in chain:
                chain.append(p)
        # 过滤不支持 openai 兼容的 provider（base is None）+ 无专属 key 的 provider 直接跳过
        filtered: list[str] = []
        for p in chain:
            base = _get_base_for_provider(p)
            if not base:
                continue
            if not _get_api_key_for_provider(p):
                continue
            filtered.append(p)
        return filtered or [self.provider]

    async def chat(self, messages: list[dict[str, Any]], **kw) -> str:
        # BYOK - 用统一入参，底层仍走 openai SDK 兼容
        # 支持 Pi 风格 fallback 链与重试隔离（对标 Pi/packages/ai/src/models.ts:667-733）
        fallback = kw.pop("fallback", True)
        max_retries = int(kw.pop("max_retries", 1))
        timeout = kw.pop("timeout", 15)
        return await self._chat_with_fallback(messages, max_retries=max_retries, timeout=timeout, fallback=fallback, **kw)

    async def chat_with_meta(self, messages: list[dict[str, Any]], **kw) -> dict:
        # S2: 返回全量 dict（含 finish_reason）供 graph planner_node 判断截断
        fallback = kw.pop("fallback", True)
        max_retries = int(kw.pop("max_retries", 1))
        timeout = kw.pop("timeout", 15)
        return await self._chat_with_fallback_meta(messages, max_retries=max_retries, timeout=timeout, fallback=fallback, **kw)

    async def _chat_with_provider(self, provider: str, messages: list[dict[str, Any]], timeout: int, explicit_model: str | None, **kw) -> dict:
        from openai import AsyncOpenAI

        cfg = PROVIDER_MAP.get(provider, PROVIDER_MAP["openai"])
        base = _get_base_for_provider(provider) or settings.llm_base_url
        api_key = _get_api_key_for_provider(provider)
        if not api_key:
            raise ValueError(f"no api key for provider {provider}")
        # Deprecated: PYTEST短路仅兼容旧测试，新测试请用 app.core.faux.FauxProvider（见test_llm_faux）
        # pytest / CI 快速短路：避免真实网络拖慢测试
        if os.getenv("PYTEST_CURRENT_TEST"):
            raise RuntimeError("PYTEST mock - skip real LLM")
        model = explicit_model or cfg.get("model") or settings.llm_model
        client = AsyncOpenAI(api_key=api_key, base_url=base)
        # openai SDK 的 timeout 通过 kw 传递，兼容 float/int
        kw.setdefault("timeout", timeout)
        resp = await client.chat.completions.create(model=model, messages=messages, **kw)
        # S2: 透出 finish_reason，异常缺省 None
        try:
            _fr = resp.choices[0].finish_reason
        except Exception:
            _fr = None
        try:
            _text = resp.choices[0].message.content or ""
        except Exception:
            _text = ""
        return {"text": _text, "finish_reason": _fr}

    async def _chat_with_fallback_meta(self, messages: list[dict[str, Any]], *, max_retries: int = 1, timeout: int = 15, fallback: bool = True, **kw) -> dict:
        explicit_model = kw.pop("model", None)
        # also pop internal marker if any
        kw.pop("_explicit_model", None)
        chain = self._build_fallback_chain(fallback)
        last_err: Exception | None = None
        for provider in chain:
            # 无专属 env key 的 provider 直接跳过（不复用全局 key 致 401 连锁）
            if not _get_api_key_for_provider(provider):
                last_err = ValueError(f"no api key for provider {provider} (skipped)")
                continue
            for attempt in range(max_retries + 1):
                try:
                    return await self._chat_with_provider(provider, messages, timeout=timeout, explicit_model=explicit_model, **kw)
                except Exception as e:
                    last_err = e
                    if attempt < max_retries and _is_retryable(e):
                        await asyncio.sleep(0.2 * (2**attempt))
                        continue
                    # 非重试错误或重试耗尽 -> 尝试下一个 provider（若有）
                    break
            # 如果不是最后一个 provider 且还有 fallback，继续下一个 provider（指数退避小延迟）
            if provider != chain[-1]:
                # 若错误是 401/403（认证失败）且 api_key 为空，快速尝试下一 provider 的独立 env key
                # 无需额外延迟，直接尝试
                await asyncio.sleep(0.1)
                continue
        if last_err:
            raise last_err
        raise RuntimeError("chat fallback chain exhausted")

    async def _chat_with_fallback(self, messages: list[dict[str, Any]], *, max_retries: int = 1, timeout: int = 15, fallback: bool = True, **kw) -> str:
        # S2: 保持返回 str 不变，内部解包 text
        meta = await self._chat_with_fallback_meta(messages, max_retries=max_retries, timeout=timeout, fallback=fallback, **kw)
        if isinstance(meta, dict):
            return str(meta.get("text", "") or "")
        return str(meta or "")

    def list_providers(self) -> list[str]:
        return list(PROVIDER_MAP.keys())

    def get_provider_config(self, provider: str) -> dict[str, Any] | None:
        return PROVIDER_MAP.get(provider)

    async def embed(self, text: str, dim: int = 1536) -> list[float]:
        try:
            from openai import AsyncOpenAI
            api_key = _get_api_key_for_provider(self.provider) or settings.llm_api_key
            base = _get_base_for_provider(self.provider) or settings.llm_base_url
            if not api_key:
                return _hash_mock_embedding(text, dim)
            client = AsyncOpenAI(api_key=api_key, base_url=base)
            resp = await client.embeddings.create(model="text-embedding-3-small", input=text)
            vec = resp.data[0].embedding
            if len(vec) != dim:
                vec = (vec[:dim] + [0.0]*dim)[:dim]
            n = math.sqrt(sum(x*x for x in vec))
            return [x/n for x in vec] if n else vec
        except Exception:
            return _hash_mock_embedding(text, dim)
