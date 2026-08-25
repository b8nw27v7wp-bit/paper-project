import json
import os
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings

settings = get_settings()

# 内存 SSE 重放存储
plan_store: dict[str, list[dict]] = {}

SYSTEM_PROMPT = """你是专业学习规划师。输入包含 goal{title,deadline,description} 与 preferences{hours_per_day}，请按以下规则生成循序渐进的学习计划，严格输出 JSON 数组，不要任何解释、Markdown 或前后缀：

输出格式（严格 JSON 数组）：
[
  {
    "title": "任务标题（具体可执行）",
    "planned_start": "YYYY-MM-DDTHH:MM:SS+00:00",
    "planned_end": "YYYY-MM-DDTHH:MM:SS+00:00",
    "priority": 1-5,
    "description": "任务详细说明，含目标与产出",
    "estimated_hours": 1.0
  }
]

约束：
- 每个任务必须包含 title/planned_start/planned_end/priority(1-5)/description/estimated_hours，estimated_hours 与 planned_start/planned_end 时长一致（1位小数）
- 任务时间不能重叠，每个任务 planned_start < planned_end 且互不交叉
- 每天总时长不超过 preferences.hours_per_day，按天均匀分配，循序渐进由易到难
- priority 1-5 区分优先级，循序渐进合理分布
- 按 goal.deadline 倒排，控制在截止前完成
- 只输出 JSON 数组。
"""

def mock_generate(goal: dict, preferences: dict, trace_id: str) -> tuple[list[dict], str]:
    hours = (preferences or {}).get("hours_per_day", 2)
    hours = max(hours, 1)
    hours = min(hours, 8)
    # 计算天数：deadline 距今，取 min(7, 剩余天数)
    try:
        dl = goal["deadline"]
        if isinstance(dl, str):
            dl = datetime.fromisoformat(dl)
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=UTC)
    except Exception:
        dl = datetime.now(UTC) + timedelta(days=7)
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    # 支持更长排期：最长14天（用户要求“排的长一些”），仍受deadline约束
    days = max(1, min(14, (dl - today).days))
    tasks = []
    base_hour = 9
    for i in range(days):
        d = today + timedelta(days=i+1)
        # 支持更长排期：每天1-2任务，单任务时长 = hours/count，保证总时长≈hours
        count = 1 if hours <= 3 else 2
        per = round(hours / count, 1)
        # 若 per>4 则仍生成，但Critic会提示超载（用于演示长任务）
        for j in range(count):
            start = d.replace(hour=base_hour + j*5, minute=0)
            end = start + timedelta(hours=per)
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
                "description": f"{goal.get('title','学习')} 第{i+1}阶段任务{j+1}：循序渐进完成",
                "estimated_hours": per,
            })
    mentor = f"已为「{goal.get('title')}」生成{len(tasks)}个任务，每天{hours}h，坚持即胜利！"
    return tasks, mentor

async def llm_generate(goal: dict, preferences: dict) -> tuple[list[dict], str]:
    # Pi 风格 fallback：若全局 key 为空但存在 provider 专属 env key 仍可尝试（对标 Pi/packages/ai/src/models.ts:448-483 credential 解析）
    has_key = bool(settings.llm_api_key) or any(
        os.getenv(k)
        for k in ["ZHIPU_API_KEY", "BIGMODEL_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    )
    if not has_key:
        raise RuntimeError("no key")
    last_err: Exception | None = None
    for attempt in range(2):  # retry 1 次（共2次尝试）- JSON 解析重试，LLM 层已含 fallback+重试
        try:
            from app.core.llm import UnifiedClient

            client = UnifiedClient()
            user_msg = f"goal={json.dumps(goal, ensure_ascii=False)}\npreferences={json.dumps(preferences or {}, ensure_ascii=False)}\n截止:{goal.get('deadline')}"
            text = await client.chat(
                [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
                model=settings.llm_model,
                temperature=0.7,
                timeout=15,
                fallback=True,
                max_retries=1,
            )
            # 提取 JSON 数组
            start = text.find("[")
            end = text.rfind("]")+1
            if start>=0 and end>start:
                try:
                    arr = json.loads(text[start:end])
                except json.JSONDecodeError as je:
                    last_err = je
                    if attempt == 0:
                        continue
                    raise
                tasks = []
                for it in arr:
                    # 优先新格式 planned_start/planned_end，否则兼容旧 date/hours
                    ps = it.get("planned_start")
                    pe = it.get("planned_end")
                    if ps and pe:
                        try:
                            s = datetime.fromisoformat(ps)
                            e = datetime.fromisoformat(pe)
                            if s.tzinfo is None:
                                s = s.replace(tzinfo=UTC)
                            if e.tzinfo is None:
                                e = e.replace(tzinfo=UTC)
                            # 校验不重叠在上层保证，此处仅解析
                            est = float(it.get("estimated_hours", (e - s).total_seconds() / 3600))
                            desc = it.get("description", "")
                        except Exception:
                            continue
                    else:
                        date = it.get("date")
                        try:
                            d = datetime.fromisoformat(date)
                            if d.tzinfo is None: d = d.replace(tzinfo=UTC)
                        except Exception:
                            d = datetime.now(UTC) + timedelta(days=1)
                        # 用 date + 默认 9点
                        s = d.replace(hour=9, minute=0, second=0, microsecond=0)
                        hours = float(it.get("hours", it.get("estimated_hours", 1)))
                        e = s + timedelta(hours=hours)
                        est = hours
                        desc = it.get("description", "")
                        ps = s.isoformat()
                        pe = e.isoformat()
                    tasks.append({
                        "title": it.get("title","学习任务"),
                        "planned_start": s.isoformat() if isinstance(s, datetime) else ps,
                        "planned_end": e.isoformat() if isinstance(e, datetime) else pe,
                        "priority": max(1, min(5, int(it.get("priority",3)))),
                        "date": s.date().isoformat() if isinstance(s, datetime) else s[:10],
                        "description": desc or f"{it.get('title','学习任务')} 循序渐进完成",
                        "estimated_hours": round(est, 1),
                    })
                if tasks:
                    return tasks, f"AI已为「{goal.get('title')}」定制{len(tasks)}个任务！"
            raise RuntimeError("parse empty")
        except Exception as e:
            last_err = e
            if attempt == 0 and isinstance(e, (json.JSONDecodeError, RuntimeError)):
                # JSON 解析失败重试 1 次
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("llm_generate failed after retry")

async def generate_plan(goal: dict, preferences: dict, trace_id: str) -> tuple[list[dict], str, str]:
    """返回 tasks, mentor_msg, source (mock|llm)"""
    # thinking trace 步骤记录
    thoughts: list[str] = []
    thoughts.append(f"思考1: 解析目标「{goal.get('title')}」截止 {goal.get('deadline')} 与偏好 {preferences}")
    hours = (preferences or {}).get("hours_per_day", 2)
    thoughts.append(f"思考2: 评估每日可用时长 {hours}h，计算剩余天数并按天分配，避免重叠与超载")
    thoughts.append("思考3: 拆解为循序渐进的子任务，确保每天总时长≤hours_per_day 且时间不重叠")
    # 先尝试 llm，失败降级 mock
    try:
        thoughts.append("思考4: 调用 LLM 生成严格 JSON 任务列表（带 retry）")
        tasks, mentor = await llm_generate(goal, preferences)
        source = "llm"
        thoughts.append(f"思考5: LLM 成功生成 {len(tasks)} 个任务，校验优先级与时长")
    except Exception as e:
        thoughts.append(f"思考4: LLM 调用失败({e})，降级 mock_generate 兜底")
        tasks, mentor = mock_generate(goal, preferences, trace_id)
        source = "mock"
        thoughts.append(f"思考5: Mock 生成 {len(tasks)} 个任务，完成兜底排期")
    # 写入 plan_store 供 SSE 重放
    events = []
    for idx, th in enumerate(thoughts, 1):
        events.append({"event":"thought","data":{"agent":"planner","step": idx,"text": th}})
    events.append({"event":"tool_call","data":{"tool":"mock_generate" if source=="mock" else "llm_generate","args":{"goal_id":goal.get("id"),"days":len({t['date'] for t in tasks})}}})
    for t in tasks:
        events.append({"event":"task_created","data":{"task":{"title":t["title"],"planned_start":t["planned_start"],"planned_end":t["planned_end"],"priority":t["priority"],"description":t.get("description",""),"estimated_hours":t.get("estimated_hours")}}})
    events.append({"event":"done","data":{"trace_id":trace_id,"count":len(tasks),"source":source}})
    plan_store[trace_id] = events
    return tasks, mentor, source
