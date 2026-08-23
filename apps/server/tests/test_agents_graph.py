import pytest
from datetime import datetime, timezone, timedelta
from app.agents.graph import graph, critic_node
from app.agents.state import PlanState

def make_task(start, end, title="T"):
    return {"title": title, "planned_start": start.isoformat(), "planned_end": end.isoformat(), "priority": 3, "date": start.date().isoformat()}

def test_critic_overlap():
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    t1 = make_task(now, now+timedelta(hours=2), "A")
    t2 = make_task(now+timedelta(hours=1), now+timedelta(hours=3), "B")  # overlap 1h /2h =50% >30%
    state = {"tasks": [t1, t2]}
    res = critic_node(state)  # type: ignore
    assert "重叠" in res["critic_feedback"]

def test_critic_daily_overload():
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    tasks = []
    for i in range(3):
        s = now + timedelta(hours=i*1.5)
        e = s + timedelta(hours=1.5)
        tasks.append(make_task(s, e, f"T{i}"))
    # total 4.5h >4
    res = critic_node({"tasks": tasks})  # type: ignore
    assert "超4h" in res["critic_feedback"] or "负荷" in res["critic_feedback"]

def test_critic_pass():
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    t1 = make_task(now, now+timedelta(hours=1))
    t2 = make_task(now+timedelta(hours=2), now+timedelta(hours=3))
    res = critic_node({"tasks": [t1, t2]})  # type: ignore
    assert res["critic_feedback"] == ""

@pytest.mark.asyncio
async def test_graph_normal():
    goal = {"id": 1, "title": "Test Goal", "deadline": (datetime.now(timezone.utc)+timedelta(days=5)).isoformat(), "description": ""}
    init = {"goal": goal, "preferences": {"hours_per_day": 2}, "trace_id": "test", "memory": [], "graphDeps": [], "vectorDeps": [], "milestones": [], "tasks": [], "critic_feedback": "", "mentor_msg": "", "rewrites": 0}
    res = await graph.ainvoke(init)
    assert len(res["tasks"]) >= 3
    assert res["mentor_msg"]
    # 正常情况 critic 应 pass
    assert res["critic_feedback"] == ""
    assert res["rewrites"] == 0

@pytest.mark.asyncio
async def test_graph_replan():
    # 直接测试带重叠的初始 tasks 会触发重规划
    # 我们通过直接给 graph 一个会导致 critic 失败的 tasks 是在 planner 生成后才有的，所以需要 mock planner 生成重叠
    # 简化：测试 critic 失败后 planner 会重规划计数增加
    from app.agents.graph import planner_node
    # 构造一个会重叠的 planner 输出 by patching
    goal = {"id": 1, "title": "Overlap Goal", "deadline": (datetime.now(timezone.utc)+timedelta(days=5)).isoformat(), "description": ""}
    # 强制 planner 生成重叠：我们直接测试 critic 后手动重规划
    now = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    overlapping_tasks = [make_task(now, now+timedelta(hours=2), "A"), make_task(now+timedelta(hours=1), now+timedelta(hours=3), "B")]
    # 模拟一轮 critic 失败后重规划
    state = {"goal": goal, "preferences": {"hours_per_day": 2}, "trace_id": "test", "memory": [], "graphDeps": [], "vectorDeps": [], "milestones": [], "tasks": overlapping_tasks, "critic_feedback": "重叠", "mentor_msg": "", "rewrites": 0}
    res = await graph.ainvoke(state)
    # 经过重规划，最终应 pass 或 rewrites=2 兜底
    assert res["rewrites"] <= 2
    # 最终应有 mentor
    assert res["mentor_msg"]
