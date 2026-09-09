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
