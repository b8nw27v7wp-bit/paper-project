"""Wave A 审批制度：Codex对标 protocol.rs:984四档 + execpolicy decision三值。

5用例：四档映射 / never直拒 / Prompt进拦截 / 规则追加幂等 / 旧布尔兼容。
纯函数 + 网关决策表为主，规则追加走真实 POST 接口（内存幂等），不跑 graph。
"""
import uuid

from fastapi.testclient import TestClient

from app.api.v1 import plans as plans_mod
from app.core.database import init_db
from app.main import app
from app.models.plan import PlanCreate
from app.services import exec_policy
from app.services.exec_policy import Decision

init_db()
client = TestClient(app)


def test_1_four_modes_mapping():
    """四档映射：approval四档归一化 + exec_policy三值前缀max() + available_decisions。"""
    # 四档归一化
    assert plans_mod._normalize_approval_mode({"approval": "untrusted"}) == "untrusted"
    assert plans_mod._normalize_approval_mode({"approval": "on-request"}) == "on-request"
    assert plans_mod._normalize_approval_mode({"approval": "never"}) == "never"
    assert plans_mod._normalize_approval_mode({"approval": "granular"}) == "granular"
    assert plans_mod._normalize_approval_mode(None) == "on-request"
    assert plans_mod._normalize_approval_mode({}) == "on-request"
    # 大小写/下划线兼容
    assert plans_mod._normalize_approval_mode({"approval": "ON_REQUEST"}) == "on-request"
    assert plans_mod._normalize_approval_mode({"approval": "on_request"}) == "on-request"
    # exec_policy 三值：初始规则 calendar写/Prompt、todo写/Allow、tasks批量>50/Forbidden
    dec, _ = exec_policy.check("calendar.create_event")
    assert dec == Decision.Prompt
    dec, _ = exec_policy.check("todo.write")
    assert dec == Decision.Allow
    dec, _ = exec_policy.check("tasks.batch:60")
    assert dec == Decision.Forbidden
    dec, _ = exec_policy.check("tasks.batch:10")
    assert dec == Decision.Allow
    # 启发回退：写Prompt、读Allow、删/批量Forbidden
    assert exec_policy.check("write_tasks")[0] == Decision.Prompt
    assert exec_policy.check("read_notes")[0] == Decision.Allow
    assert exec_policy.check("delete_task")[0] == Decision.Forbidden
    # available_decisions：Allow时["approve","reject"]，高危时["reject","approve_with_condition"]
    assert plans_mod._approval_available_decisions(Decision.Allow) == ["approve", "reject"]
    assert plans_mod._approval_available_decisions(Decision.Prompt) == ["reject", "approve_with_condition"]
    assert plans_mod._approval_available_decisions(Decision.Forbidden) == ["reject", "approve_with_condition"]


def test_2_never_direct_reject():
    """never直拒：never下Prompt自动降Forbidden，handling=forbidden（直接拒，不进Redis）。"""
    dec, handling = plans_mod._decide_gateway("calendar.create_event", "never", False)
    assert dec == Decision.Forbidden
    assert handling == "forbidden"
    # 批量>50 本就是 Forbidden，never 下仍直拒
    dec2, handling2 = plans_mod._decide_gateway("tasks.batch:60", "never", False)
    assert dec2 == Decision.Forbidden
    assert handling2 == "forbidden"
    # 同一 Prompt 动作在 on-request 下本应 prompt，never 下降级为 forbidden
    dec3, handling3 = plans_mod._decide_gateway("calendar.create_event", "on-request", True)
    assert handling3 == "prompt"
    assert (dec, handling) != (dec3, handling3)


def test_3_prompt_goes_intercept():
    """Prompt进拦截：Prompt+need_approval=True走Redis拦截；Allow直行；无need_approval则放行。"""
    dec, handling = plans_mod._decide_gateway("calendar.create_event", "on-request", True)
    assert dec == Decision.Prompt
    assert handling == "prompt"
    # 同动作无 need_approval 时直行 allow（不进拦截）
    dec2, handling2 = plans_mod._decide_gateway("calendar.create_event", "on-request", False)
    assert handling2 == "allow"
    # Allow 动作即使 need_approval=True 仍直行
    dec3, handling3 = plans_mod._decide_gateway("todo.write", "on-request", True)
    assert dec3 == Decision.Allow
    assert handling3 == "allow"
    # Forbidden 任何情况下直拒
    dec4, handling4 = plans_mod._decide_gateway("tasks.batch:60", "on-request", True)
    assert dec4 == Decision.Forbidden
    assert handling4 == "forbidden"


def test_4_rule_append_idempotent():
    """规则追加幂等：POST approve-rule 同prefix+同decision两次返回一致，check生效，清理不污染全局。"""
    trace_id = "t-" + uuid.uuid4().hex[:12]
    prefix = "test.idempotent." + uuid.uuid4().hex[:8]
    body = {"prefix": prefix, "decision": "Prompt"}
    r1 = client.post(f"/api/v1/plans/{trace_id}/approve-rule", json=body)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["prefix"] == prefix
    assert d1["decision"] == "Prompt"
    r2 = client.post(f"/api/v1/plans/{trace_id}/approve-rule", json=body)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()["data"]
    assert d2 == d1
    # 追加后 check 生效（前缀max命中新规则）
    dec, _ = exec_policy.check(prefix + ".do_something")
    assert dec == Decision.Prompt
    # 非法输入 400
    r_bad = client.post(f"/api/v1/plans/{trace_id}/approve-rule", json={"prefix": "", "decision": "Prompt"})
    assert r_bad.status_code == 400
    r_bad2 = client.post(f"/api/v1/plans/{trace_id}/approve-rule", json={"prefix": prefix, "decision": "bogus"})
    assert r_bad2.status_code == 400
    # 清理
    try:
        exec_policy._PREFIX_RULES.pop(prefix, None)
    except Exception:
        pass


def test_5_legacy_bool_compat():
    """旧布尔兼容：require_approval=true→untrusted；need_approval旧变量保留映射；默认不拦截。"""
    # 旧布尔 true 归一为 untrusted
    p_old = PlanCreate(goal_id=1, require_approval=True)
    assert plans_mod._normalize_approval_mode(p_old) == "untrusted"
    assert plans_mod._resolve_need_approval("untrusted", p_old) is True
    # 默认（无显式请求）归一 on-request 但 need_approval=False（旧流程零改动）
    p_def = PlanCreate(goal_id=1)
    assert plans_mod._normalize_approval_mode(p_def) == "on-request"
    assert plans_mod._resolve_need_approval("on-request", p_def) is False
    # 显式 approval 优先于旧布尔；never 永不拦截
    p_never = PlanCreate(goal_id=1, approval="never")
    assert plans_mod._normalize_approval_mode(p_never) == "never"
    assert plans_mod._resolve_need_approval("never", p_never) is False
    p_gran = PlanCreate(goal_id=1, approval="granular")
    assert plans_mod._normalize_approval_mode(p_gran) == "granular"
    assert plans_mod._resolve_need_approval("granular", p_gran) is True
    # 网关侧：旧布尔兼容映射后 Prompt 仍进拦截
    mode = plans_mod._normalize_approval_mode(p_old)
    need = plans_mod._resolve_need_approval(mode, p_old)
    _, handling = plans_mod._decide_gateway("calendar.create_event", mode, need)
    assert handling == "prompt"


def test_6_approve_rule_owner_403():
    """Wave1 P0：approve-rule 跨用户 403（复用 _enforce_trace_owner/_TRACE_OWNERS），全局表保留。"""
    tid = "t-owner-" + uuid.uuid4().hex[:12]
    prefix = "test.owner." + uuid.uuid4().hex[:8]
    try:
        plans_mod._TRACE_OWNERS[tid] = 1
        # 本人 200（全局表写入）
        r_ok = client.post(f"/api/v1/plans/{tid}/approve-rule", json={"prefix": prefix, "decision": "Allow"})
        assert r_ok.status_code == 200, r_ok.text
        assert r_ok.json()["data"]["prefix"] == prefix
        # 跨用户 403（X-User-Id=2，经 _enforce_trace_owner 404 转 403）
        r_cross = client.post(f"/api/v1/plans/{tid}/approve-rule", json={"prefix": prefix, "decision": "Allow"}, headers={"X-User-Id": "2"})
        assert r_cross.status_code == 403, r_cross.text
        # 未知 trace（无归属）放行 200（旧 test_4 兼容）
        r_unknown = client.post("/api/v1/plans/t-unknown-%s/approve-rule" % uuid.uuid4().hex[:8], json={"prefix": prefix + ".x", "decision": "Allow"})
        assert r_unknown.status_code == 200, r_unknown.text
    finally:
        try:
            plans_mod._TRACE_OWNERS.pop(tid, None)
        except Exception:
            pass
        try:
            exec_policy._PREFIX_RULES.pop(prefix, None)
        except Exception:
            pass
        try:
            exec_policy._PREFIX_RULES.pop(prefix + ".x", None)
        except Exception:
            pass


def test_7_cache_user_binding_dualwrite():
    """Wave1 P0：cache user绑定写双写新旧键、读优先新键（旧键只读兼容）。"""
    from app.core import cache as cache_mod

    tid = "t-cache-" + uuid.uuid4().hex[:12]
    evs = [{"event": "thought", "data": {"agent": "planner", "text": "hi"}}]
    g = {"nodes": [{"id": "planner"}], "edges": [], "status": "running", "trace_id": tid}
    try:
        plans_mod._cache_set_workbench_user(tid, evs, 1)
        plans_mod._cache_set_graph_user(tid, g, 1)
        # 新键命中（user绑定）
        assert cache_mod.get_workbench(tid, user_id=1) == evs
        assert cache_mod.get_graph(tid, user_id=1) == g
        # 旧键保留只读兼容（不传 user_id 仍可读）
        assert cache_mod.get_workbench(tid) == evs
        assert cache_mod.get_graph(tid) == g
        # 严格绑定：错用户读新键为 None（不回退，由路由层先鉴权）
        assert cache_mod.get_workbench(tid, user_id=2) is None
        assert cache_mod.get_graph(tid, user_id=2) is None
        # plans 侧优先读：本人优先新键
        assert plans_mod._cache_get_workbench_user(tid, 1) == evs
        assert plans_mod._cache_get_graph_user(tid, 1) == g
        # 旧 trace（仅旧键）经 plans 侧回读兼容
        tid_old = "t-cache-old-" + uuid.uuid4().hex[:8]
        cache_mod.set_workbench(tid_old, evs)
        assert plans_mod._cache_get_workbench_user(tid_old, 1) == evs
    finally:
        pass


def test_8_llm_meta_3tuple_and_has_key():
    """Wave1 P0：mock 3元 + has_key 去 ANTHROPIC（与 fallback 过滤一致）。"""
    import inspect

    import app.agents.graph as graph_mod
    from app.services.planner import mock_generate

    goal = {"title": "G", "deadline": "2026-09-20T00:00:00+00:00"}
    out = mock_generate(goal, {"hours_per_day": 2}, "t-x")
    assert isinstance(out, (list, tuple)) and len(out) == 3
    tasks, mentor, meta = out
    assert isinstance(tasks, list) and tasks
    assert isinstance(meta, dict) and meta == {}
    src = inspect.getsource(graph_mod._try_llm_critic)
    assert "ANTHROPIC_API_KEY" not in src
    # planner_node 不读模块全局（删全局依赖：无 _planner_mod/last_meta 回读）
    src2 = inspect.getsource(graph_mod.planner_node)
    assert "_planner_mod" not in src2
    assert "last_meta" not in src2


def test_9_approve_rules_list_and_delete():
    """Wave A 规则列表/删除：增后列表可见 / 重复增幂等 / 删除后列表无 / 删不存在 deleted:false / 空prefix 400。"""
    trace_id = "t-" + uuid.uuid4().hex[:12]
    prefix = "test.rules." + uuid.uuid4().hex[:8]
    try:
        # 增后列表可见
        r_add = client.post(f"/api/v1/plans/{trace_id}/approve-rule", json={"prefix": prefix, "decision": "Prompt"})
        assert r_add.status_code == 200, r_add.text
        r_list = client.get("/api/v1/plans/approve-rules")
        assert r_list.status_code == 200, r_list.text
        body = r_list.json()
        assert body["code"] == 200
        data = body["data"]
        assert "rules" in data and "total" in data
        hit = [x for x in data["rules"] if x.get("prefix") == prefix]
        assert len(hit) == 1
        assert hit[0]["decision"] == "Prompt"
        assert isinstance(hit[0].get("justification"), str)
        total_before = data["total"]
        # 重复增幂等（同 prefix+同 decision）：列表 total 不变、无重复条目
        r_dup = client.post(f"/api/v1/plans/{trace_id}/approve-rule", json={"prefix": prefix, "decision": "Prompt"})
        assert r_dup.status_code == 200, r_dup.text
        r_list2 = client.get("/api/v1/plans/approve-rules")
        assert r_list2.status_code == 200, r_list2.text
        data2 = r_list2.json()["data"]
        assert data2["total"] == total_before
        assert len([x for x in data2["rules"] if x.get("prefix") == prefix]) == 1
        # 删除后列表无
        r_del = client.request("DELETE", "/api/v1/plans/approve-rules", json={"prefix": prefix})
        assert r_del.status_code == 200, r_del.text
        assert r_del.json()["data"] == {"deleted": True}
        r_list3 = client.get("/api/v1/plans/approve-rules")
        assert r_list3.status_code == 200, r_list3.text
        assert all(x.get("prefix") != prefix for x in r_list3.json()["data"]["rules"])
        # 删不存在返回 deleted:false 200（幂等）
        r_del2 = client.request("DELETE", "/api/v1/plans/approve-rules", json={"prefix": prefix})
        assert r_del2.status_code == 200, r_del2.text
        assert r_del2.json()["data"] == {"deleted": False}
        # 空 prefix 40001
        r_bad = client.request("DELETE", "/api/v1/plans/approve-rules", json={"prefix": ""})
        assert r_bad.status_code == 400, r_bad.text
        assert r_bad.json()["code"] == 40001
    finally:
        try:
            exec_policy._PREFIX_RULES.pop(prefix, None)
        except Exception:
            pass


def test_10_approve_rules_unauth_401(monkeypatch):
    """Wave A 规则列表/删除未登录 401（prod 鉴权强拒：debug=False + 无 PYTEST 回退）。"""
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "debug", False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    r = client.get("/api/v1/plans/approve-rules")
    assert r.status_code == 401, r.text
    assert r.json()["code"] == 40101
    r2 = client.request("DELETE", "/api/v1/plans/approve-rules", json={"prefix": "test.noauth"})
    assert r2.status_code == 401, r2.text
    assert r2.json()["code"] == 40101


def test_11_approval_rules_persist_reload():
    """审批规则持久化：add→save→清内存→load 可见；remove→save→清内存→load 不可见。"""
    from sqlmodel import Session

    from app.core.database import engine

    backup = dict(exec_policy._PREFIX_RULES)
    prefix = "test.persist." + uuid.uuid4().hex[:8]
    try:
        exec_policy.add_rule(prefix, "Allow", "persist-test")
        with Session(engine) as s:
            assert exec_policy.save_to_db(s) is True
        # 模拟重启：清空内存后重载可见
        exec_policy._PREFIX_RULES.clear()
        assert prefix not in exec_policy._PREFIX_RULES
        with Session(engine) as s:
            assert exec_policy.load_from_db(s) is True
        assert prefix in exec_policy._PREFIX_RULES
        assert exec_policy.check(prefix + ".do")[0] == Decision.Allow
        # remove 后重载不可见
        assert exec_policy.remove_rule(prefix) is True
        with Session(engine) as s:
            assert exec_policy.save_to_db(s) is True
        exec_policy._PREFIX_RULES.clear()
        with Session(engine) as s:
            exec_policy.load_from_db(s)
        assert prefix not in exec_policy._PREFIX_RULES
    finally:
        try:
            exec_policy._PREFIX_RULES.clear()
            exec_policy._PREFIX_RULES.update(backup)
        except Exception:
            pass
        try:
            with Session(engine) as s:
                exec_policy.save_to_db(s)
        except Exception:
            pass


def test_12_approval_rules_db_failure_memory_ok():
    """DB 不可用时内存照常工作：save/load 返回 False 不抛，内存规则不受影响。"""

    class _BadSession:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

        def commit(self):
            raise RuntimeError("db down")

        def rollback(self):
            return None

    backup = dict(exec_policy._PREFIX_RULES)
    prefix = "test.dbfail." + uuid.uuid4().hex[:8]
    try:
        dec, _ = exec_policy.add_rule(prefix, "Prompt")
        assert dec == Decision.Prompt
        assert exec_policy.check(prefix + ".x")[0] == Decision.Prompt
        # save 失败只返回 False，不抛，内存保留
        assert exec_policy.save_to_db(_BadSession()) is False
        assert prefix in exec_policy._PREFIX_RULES
        before = dict(exec_policy._PREFIX_RULES)
        # load 失败返回 False，内存不变
        assert exec_policy.load_from_db(_BadSession()) is False
        assert exec_policy._PREFIX_RULES == before
        # remove 内存照常
        assert exec_policy.remove_rule(prefix) is True
        assert prefix not in exec_policy._PREFIX_RULES
        assert exec_policy.load_from_db(None) is False
        assert exec_policy.save_to_db(None) is False
    finally:
        try:
            exec_policy._PREFIX_RULES.clear()
            exec_policy._PREFIX_RULES.update(backup)
        except Exception:
            pass
