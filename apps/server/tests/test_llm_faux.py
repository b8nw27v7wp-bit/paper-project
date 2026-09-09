"""S2/S3/S9: length截断透出 / cost统计 / 配额不重试（FauxProvider 仅供新测试用）"""
import pytest

import app.core.llm as llm_mod
from app.core.faux import FauxProvider


@pytest.mark.asyncio
async def test_length_truncation_propagates(monkeypatch):
    # Faux length 透出 + 空则复最后一条
    faux = FauxProvider(
        [
            {"text": '[{"title":"x"}]', "finish_reason": "length", "usage": {"total_tokens": 10}, "cost": 0.001},
        ]
    )
    res = await faux.chat([{"role": "user", "content": "hi"}])
    assert res["finish_reason"] == "length"
    assert "x" in res["text"]
    res2 = await faux.chat([{"role": "user", "content": "hi2"}])
    assert res2["finish_reason"] == "length"

    # UnifiedClient.chat_with_meta 透出 length，chat() 保持 str（内部解包 text）
    async def _fake_provider(self, provider, messages, timeout, explicit_model, **kw):
        return {"text": "partial", "finish_reason": "length"}

    monkeypatch.setattr(llm_mod.UnifiedClient, "_chat_with_provider", _fake_provider)
    monkeypatch.setattr(llm_mod, "_get_api_key_for_provider", lambda p: "k")
    monkeypatch.setattr(llm_mod, "_get_base_for_provider", lambda p: "http://x")
    c = llm_mod.UnifiedClient(provider="openai")
    meta = await c.chat_with_meta([{"role": "user", "content": "hi"}])
    assert meta["finish_reason"] == "length"
    assert meta["text"] == "partial"
    txt = await c.chat([{"role": "user", "content": "hi"}])
    assert isinstance(txt, str) and txt == "partial"

    # graph planner_node length 丢弃本批：tasks=[]、thought 记截断丢弃待重发
    import app.agents.graph as graph_mod
    import app.services.planner as planner_mod

    async def _fake_llm(goal, prefs):
        return (
            [{"title": "t", "planned_start": "2026-09-10T09:00:00+00:00", "planned_end": "2026-09-10T10:00:00+00:00"}],
            "m",
            {"text": "x", "finish_reason": "length"},
        )

    monkeypatch.setattr(planner_mod, "llm_generate", _fake_llm)
    monkeypatch.setattr(graph_mod, "llm_generate", _fake_llm)
    state = {
        "goal": {"title": "G", "deadline": "2026-09-20T00:00:00+00:00"},
        "preferences": {"hours_per_day": 2},
        "rewrites": 0,
        "memory": [],
        "vectorDeps": [],
        "graphDeps": [],
    }
    out = await graph_mod.planner_node(state)  # type: ignore[arg-type]
    # Pi对标length整批失败→重发：截断batch不可信，mock兜底重发保证非空计划
    assert len(out["tasks"]) > 0
    assert "重发" in out["_thought"]


@pytest.mark.asyncio
async def test_cost_accounting():
    # Faux usage/cost 透出
    faux = FauxProvider(
        [
            {"text": "a", "finish_reason": "stop", "usage": {"total_tokens": 100}, "cost": 0.002},
            {"text": "b", "finish_reason": "stop", "usage": {"total_tokens": 200}, "cost": 0.004},
        ]
    )
    r1 = await faux.chat([{"role": "user", "content": "1"}])
    r2 = await faux.chat([{"role": "user", "content": "2"}])
    assert r1["cost"] == pytest.approx(0.002)
    assert r2["cost"] == pytest.approx(0.004)
    assert r1["usage"] == {"total_tokens": 100}
    assert (r1["cost"] + r2["cost"]) == pytest.approx(0.006)
    # 空则复最后一条（cost 复用）
    r3 = await faux.chat([{"role": "user", "content": "3"}])
    assert r3["cost"] == pytest.approx(0.004)

    # stats overflow 独立计数，旧字段不动
    from app.services import stats as stats_mod

    stats_mod.reset_overflow_count()
    assert stats_mod.get_overflow_count() == 0
    stats_mod.record_overflow(2)
    assert stats_mod.get_overflow_count() == 2
    stats_mod.record_overflow()
    assert stats_mod.get_overflow_count() == 3
    stats_mod.reset_overflow_count()
    assert stats_mod.get_overflow_count() == 0


async def test_quota_not_retryable(monkeypatch):
    from app.core.llm import NON_RETRYABLE, _is_retryable

    lowers = [str(s).lower() for s in NON_RETRYABLE]
    assert "insufficient_quota" in lowers
    assert "billing" in lowers
    assert "gousagelimit" in lowers
    assert "account_deactivated" in lowers

    class _E(Exception):
        pass

    assert _is_retryable(_E("insufficient_quota exceeded")) is False
    assert _is_retryable(_E("Billing hard limit")) is False
    assert _is_retryable(_E("account_deactivated")) is False
    assert _is_retryable(_E("GoUsageLimit reached")) is False
    # 401 + 配额直接 False
    e401 = _E("insufficient_quota")
    e401.status_code = 401  # type: ignore[attr-defined]
    assert _is_retryable(e401) is False
    # 可重试仍 True
    assert _is_retryable(_E("timeout boom")) is True
    assert _is_retryable(_E("429 rate limit")) is True

    # _chat_with_fallback 配额不重试：max_retries=2 也只调一次
    calls = {"n": 0}

    async def _boom(self, provider, messages, timeout, explicit_model, **kw):
        calls["n"] += 1
        raise _E("insufficient_quota stop")

    monkeypatch.setattr(llm_mod.UnifiedClient, "_chat_with_provider", _boom)
    monkeypatch.setattr(llm_mod, "_get_api_key_for_provider", lambda p: "k")
    monkeypatch.setattr(llm_mod, "_get_base_for_provider", lambda p: "http://x")
    c = llm_mod.UnifiedClient(provider="openai")
    with pytest.raises(Exception) as exc:
        await c.chat([{"role": "user", "content": "hi"}], fallback=False, max_retries=2)
    assert "insufficient_quota" in str(exc.value).lower()
    assert calls["n"] == 1
