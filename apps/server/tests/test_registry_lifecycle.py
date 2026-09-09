"""S1/S4/S5-registry/S6 生命周期用例：after全量替换/every批终止/prepare归一/execution_mode声明。"""
from __future__ import annotations

from app.agents.tools import registry


async def _dummy_fn(**kw):
    return {"orig": 1}


def _save_hooks():
    return (list(registry._before_hooks), list(registry._after_hooks))


def _restore_hooks(saved):
    b, a = saved
    registry._before_hooks[:] = b
    registry._after_hooks[:] = a


def _isolate_hooks():
    """Pi every()对标：terminate共识按全注册hook表统计，单测须清空常驻hook（如审批guard）再自建，避免导入顺序污染。"""
    saved = _save_hooks()
    registry._before_hooks[:] = []
    registry._after_hooks[:] = []
    return saved


async def test_after_full_replace_details_usage():
    saved = _save_hooks()
    registry._tools["lifecycle_dummy"] = registry.RegisteredTool(
        name="lifecycle_dummy", fn=_dummy_fn, label="dummy",
    )
    try:
        def _after(name, args, ctx, result):
            if name != "lifecycle_dummy":
                return None
            return {
                "content": {"replaced": True},
                "details": {"note": "d1"},
                "usage": {"tokens": 7},
            }

        registry.add_after_hook(_after)
        before_n = len(registry.get_events(limit=200))
        res = await registry.execute_tool("lifecycle_dummy", {})
        assert res["is_error"] is False
        # content全量替换 + usage并入result字典（dict则update usage键）
        assert isinstance(res["result"], dict)
        assert res["result"].get("replaced") is True
        assert res["result"].get("usage") == {"tokens": 7}
        # usage/details透传到顶层
        assert res.get("usage") == {"tokens": 7}
        assert res.get("details") == {"note": "d1"}
        # details并入事件data
        evs = registry.get_events(limit=20)
        assert evs, "expected TOOL_CALL_END event"
        last = evs[-1]
        assert last.data.get("note") == "d1"
        assert last.data.get("details") == {"note": "d1"}
        assert last.data.get("usage") == {"tokens": 7}
        assert len(registry.get_events(limit=200)) > before_n
    finally:
        _restore_hooks(saved)
        registry._tools.pop("lifecycle_dummy", None)


async def test_every_batch_terminate_semantics():
    saved = _isolate_hooks()
    registry._tools["lifecycle_dummy2"] = registry.RegisteredTool(
        name="lifecycle_dummy2", fn=_dummy_fn, label="dummy2",
    )
    try:
        # 全员terminate==true -> 标注terminated=true
        registry.add_before_hook(lambda n, a, c: {"terminate": True} if n == "lifecycle_dummy2" else None)
        registry.add_before_hook(lambda n, a, c: {"terminate": True} if n == "lifecycle_dummy2" else None)
        res = await registry.execute_tool("lifecycle_dummy2", {})
        assert res["is_error"] is False
        assert res.get("terminated") is True
        evs = registry.get_events(limit=5)
        assert evs[-1].data.get("terminated") is True

        # 非全员terminate -> 不标注（单个terminate不能终止批）
        _restore_hooks(saved)
        registry.add_before_hook(lambda n, a, c: {"terminate": True} if n == "lifecycle_dummy2" else None)
        registry.add_before_hook(lambda n, a, c: None)
        res2 = await registry.execute_tool("lifecycle_dummy2", {})
        assert res2["is_error"] is False
        assert res2.get("terminated") is not True

        # 单个block仅该工具失败返回（不中断其他工具语义：本函数单调用只需返回blocked）
        _restore_hooks(saved)
        registry.add_before_hook(lambda n, a, c: {"block": True, "reason": "nope"} if n == "lifecycle_dummy2" else None)
        registry.add_before_hook(lambda n, a, c: None)
        res3 = await registry.execute_tool("lifecycle_dummy2", {})
        assert res3["is_error"] is True
        assert res3.get("blocked") is True
        assert res3.get("terminated") is not True
    finally:
        _restore_hooks(saved)
        registry._tools.pop("lifecycle_dummy2", None)


async def test_prepare_alias_normalization():
    # 直接函数级：q→query、limit/top_k互通、end:None删键
    assert registry._prepare_search_args({"q": "hi", "limit": 2})["query"] == "hi"
    norm = registry._prepare_search_args({"q": "hi", "limit": 2})
    assert norm["top_k"] == 2 and norm["limit"] == 2
    norm2 = registry._prepare_search_args({"query": "x", "top_k": 4})
    assert norm2["limit"] == 4
    cal = registry._prepare_calendar_args({"title": "t", "start": "2026-09-10T09:00:00+00:00", "end": None})
    assert "end" not in cal
    # prepare失败回退原args：给一个会抛错的prepare，execute_tool仍走原逻辑
    saved = _save_hooks()
    orig_prep = registry.get_registered("web_search").prepare_arguments
    try:
        def _boom(d):
            raise RuntimeError("boom")
        registry.get_registered("web_search").prepare_arguments = _boom
        res = await registry.execute_tool("web_search", {"query": "fallback-ok", "top_k": 2})
        assert res["is_error"] is False
    finally:
        registry.get_registered("web_search").prepare_arguments = orig_prep
        _restore_hooks(saved)
    # 经execute_tool别名归一：q别名应通过校验并成功
    res2 = await registry.execute_tool("web_search", {"q": "alias-test", "limit": 2})
    assert res2["is_error"] is False
    res3 = await registry.execute_tool(
        "calendar_create",
        {"title": "PrepT", "start": "2026-09-10T09:00:00+00:00", "end": None},
    )
    assert res3["is_error"] is False


async def test_execution_mode_declaration():
    assert registry.get_registered("write_tasks").execution_mode == "sequential"
    assert registry.get_registered("calendar_create").execution_mode == "sequential"
    assert registry.get_registered("memory_search").execution_mode == "parallel"
    assert registry.get_registered("rag_search").execution_mode == "parallel"
    assert registry.get_registered("graph_search").execution_mode == "parallel"
    detailed = {d["name"]: d for d in registry.list_tools_detailed()}
    assert detailed["write_tasks"]["execution_mode"] == "sequential"
    assert detailed["memory_search"]["execution_mode"] == "parallel"
    # S5：每个占位工具附diagnostics字段（空表正常）
    for name, d in detailed.items():
        assert "diagnostics" in d, f"{name} missing diagnostics"
        assert isinstance(d["diagnostics"], list), f"{name} diagnostics not list"
    # frontmatter缺失应记diagnostics
    _, miss = registry._parse_skill_frontmatter("# no frontmatter\n")
    assert any("frontmatter" in m for m in miss)
    _, miss2 = registry._parse_skill_frontmatter("---\nname: x\n---\n")
    assert any("description" in m for m in miss2)
    _, miss3 = registry._parse_skill_frontmatter("---\nname: x\ndescription: y\n---\n# ok")
    assert miss3 == []
