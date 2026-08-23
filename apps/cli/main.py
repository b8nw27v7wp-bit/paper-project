import typer
import httpx
import rich
from rich.console import Console
from rich.table import Table
from rich.json import JSON

app = typer.Typer(help="Learning Planner CLI - Trace工具")
console = Console()

BASE = "http://localhost:8000"

@app.command()
def trace(goal: int = typer.Option(1, help="goal_id")):
    """查看某目标的最近规划轨迹"""
    with httpx.Client(base_url=BASE, timeout=10) as c:
        # 查 goals 详情含任务
        r = c.get(f"/api/v1/goals/{goal}")
        if r.status_code != 200:
            console.print(f"[red]goal {goal} 不存在[/red]")
            raise typer.Exit(1)
        console.print(JSON.from_data(r.json()))
        # 查最近的 plans logs：需先找 trace_ids via logs? 简化：查 tasks
        console.print("[green]最近任务:[/green]")
        r2 = c.get(f"/api/v1/tasks?goal_id={goal}&page=1&size=5")
        console.print(JSON.from_data(r2.json()))

@app.command()
def health():
    with httpx.Client(base_url=BASE) as c:
        r = c.get("/health")
        console.print(JSON.from_data(r.json()))

@app.command()
def plans(goal: int = typer.Option(1, help="goal_id")):
    """触发规划"""
    with httpx.Client(base_url=BASE, timeout=15) as c:
        r = c.post("/api/v1/plans", json={"goal_id": goal})
        console.print(JSON.from_data(r.json()))

if __name__ == "__main__":
    app()
