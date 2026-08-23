import json
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings

settings = get_settings()

# 内存 SSE 重放存储
plan_store: dict[str, list[dict]] = {}

SYSTEM_PROMPT = """你是学习规划师。输入 goal{title,deadline,description} 和 preferences{hours_per_day}，
按截止日期生成未来7天的每日任务，输出严格JSON数组: [{"title":"...","date":"YYYY-MM-DD","priority":1-5,"hours":1.0}]
要求可执行、标题具体、优先级区分。只输出JSON，不要解释。
"""

def mock_generate(goal: dict, preferences: dict, trace_id: str) -> tuple[list[dict], str]:
    hours = (preferences or {}).get("hours_per_day", 2)
    hours = max(hours, 1)
    hours = min(hours, 8)
    # 计算天数：deadline 距今，取 min(7, 剩余天数)
    try:
        dl = goal["deadline"]
        if isinstance(dl, str):
            dl = datetime.fromisoformat(dl.replace("Z", "+00:00"))
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=UTC)
    except Exception:
        dl = datetime.now(UTC) + timedelta(days=7)
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    days = max(1, min(7, (dl - today).days))
    tasks = []
    base_hour = 9
    for i in range(days):
        d = today + timedelta(days=i+1)
        # 每天1-2任务按hours决定
        count = 1 if hours <= 2 else 2
        for j in range(count):
            start = d.replace(hour=base_hour + j*5, minute=0)
            end = start + timedelta(hours=1 if count==2 else hours)
            # 标题结合goal title
            title = f"{goal.get('title','学习')} - 任务 {i+1}-{j+1}"
            if j == 0 and goal.get("description"):
                title = f"{goal['title']}：学习阶段 {i+1}"
            tasks.append({
                "title": title,
                "planned_start": start.isoformat(),
                "planned_end": end.isoformat(),
                "priority": 4 if j==0 else 3,
                "date": d.date().isoformat(),
            })
    mentor = f"已为「{goal.get('title')}」生成{len(tasks)}个任务，每天{hours}h，坚持即胜利！"
    return tasks, mentor

async def llm_generate(goal: dict, preferences: dict) -> tuple[list[dict], str]:
    if not settings.llm_api_key:
        raise RuntimeError("no key")
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        user_msg = f"goal={json.dumps(goal, ensure_ascii=False)}\npreferences={json.dumps(preferences or {}, ensure_ascii=False)}\n截止:{goal.get('deadline')}"
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":user_msg}],
            temperature=0.7,
            timeout=15,
        )
        text = resp.choices[0].message.content or ""
        # 提取 JSON 数组
        start = text.find("[")
        end = text.rfind("]")+1
        if start>=0 and end>start:
            arr = json.loads(text[start:end])
            tasks = []
            for it in arr:
                date = it.get("date")
                try:
                    d = datetime.fromisoformat(date)
                    if d.tzinfo is None: d = d.replace(tzinfo=UTC)
                except Exception:
                    d = datetime.now(UTC) + timedelta(days=1)
                # 用 date + 默认 9点
                s = d.replace(hour=9, minute=0, second=0, microsecond=0)
                hours = float(it.get("hours", 1))
                e = s + timedelta(hours=hours)
                tasks.append({
                    "title": it.get("title","学习任务"),
                    "planned_start": s.isoformat(),
                    "planned_end": e.isoformat(),
                    "priority": int(it.get("priority",3)),
                    "date": d.date().isoformat(),
                })
            if tasks:
                return tasks, f"AI已为「{goal.get('title')}」定制{len(tasks)}个任务！"
        raise RuntimeError("parse empty")
    except Exception as e:
        raise e

async def generate_plan(goal: dict, preferences: dict, trace_id: str) -> tuple[list[dict], str, str]:
    """返回 tasks, mentor_msg, source (mock|llm)"""
    # 先尝试 llm，失败降级 mock
    try:
        tasks, mentor = await llm_generate(goal, preferences)
        source = "llm"
    except Exception:
        tasks, mentor = mock_generate(goal, preferences, trace_id)
        source = "mock"
    # 写入 plan_store 供 SSE 重放
    events = []
    events.append({"event":"thought","data":{"agent":"planner","text":f"分析目标「{goal.get('title')}」剩余时间，生成周计划..."}})
    events.append({"event":"tool_call","data":{"tool":"mock_generate" if source=="mock" else "llm_generate","args":{"goal_id":goal.get("id"),"days":len(set(t['date'] for t in tasks))}}})
    for t in tasks:
        events.append({"event":"task_created","data":{"task":{"title":t["title"],"planned_start":t["planned_start"],"planned_end":t["planned_end"],"priority":t["priority"]}}})
    events.append({"event":"done","data":{"trace_id":trace_id,"count":len(tasks),"source":source}})
    plan_store[trace_id] = events
    return tasks, mentor, source
