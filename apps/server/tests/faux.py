"""Pi faux启示：预设轨迹，无Key也可测"""
from typing import List, Dict

FAUX_PLANNER_TASKS = [
    {"title": "Faux 任务1", "planned_start": "2026-08-24T09:00:00+00:00", "planned_end": "2026-08-24T11:00:00+00:00", "priority": 4, "date": "2026-08-24"},
    {"title": "Faux 任务2", "planned_start": "2026-08-25T09:00:00+00:00", "planned_end": "2026-08-25T11:00:00+00:00", "priority": 3, "date": "2026-08-25"},
]

async def faux_llm_generate(goal: dict, prefs: dict):
    return FAUX_PLANNER_TASKS, "Faux 激励"

def patch_llm_for_test(monkeypatch):
    # 将 planner.py 的 llm_generate 替为 faux
    import app.services.planner as p
    monkeypatch.setattr(p, "llm_generate", faux_llm_generate)
    import app.agents.graph as g
    monkeypatch.setattr(g, "llm_generate", faux_llm_generate)
