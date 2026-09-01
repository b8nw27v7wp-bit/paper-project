import json, os, sys, io, typer, httpx
from rich.console import Console
from rich.table import Table
from rich.json import JSON

# GBK 修复：强制 stdin/stdout/stderr UTF-8，Rich 关闭 legacy Windows 模式
try:
    if hasattr(sys.stdin, "reconfigure"):
        if sys.stdin.encoding and sys.stdin.encoding.lower() != "utf-8":
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")  # type: ignore
    if hasattr(sys.stdout, "reconfigure"):
        if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")  # type: ignore
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass
os.environ.setdefault("PYTHONUTF8", "1")
try:
    os.system("chcp 65001 >nul 2>&1")
except Exception:
    pass

app = typer.Typer(help="Learning Planner CLI - Trace工具 (P2/P3)", invoke_without_command=True, no_args_is_help=False)
try:
    console = Console(legacy_windows=False, force_terminal=True)
except Exception:
    console = Console()

BASE = os.getenv("PLANNER_API", "http://localhost:8000")  # 三端统一 PLANNER_API
TOKEN = os.getenv("PLANNER_TOKEN", "")

def _headers(extra: dict | None = None):
    h = {"X-User-Id": "1"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    else:
        # 尝试从本地文件读取 token（与前端 localStorage 对齐，Electron 托盘亦可写文件）
        try:
            p = os.path.expanduser("~/.planner_token")
            if os.path.exists(p):
                t = open(p, encoding="utf-8").read().strip()
                if t:
                    h["Authorization"] = f"Bearer {t}"
        except: pass
    if extra:
        h.update(extra)
    return h

def _client(): return httpx.Client(base_url=BASE, timeout=12, headers=_headers())
def _client_sse(): return httpx.Client(base_url=BASE, timeout=30, headers=_headers({"Accept": "text/event-stream"}))
def _print(data, as_json, title=""):
    if as_json: console.print_json(json.dumps(data, ensure_ascii=False))
    else:
        if title: console.print(f"[bold cyan]{title}[/bold cyan]")
        console.print(JSON.from_data(data))
def _table(rows, cols, title):
    t = Table(title=title, show_header=True, header_style="bold magenta")
    for c in cols: t.add_column(c)
    for r in rows: t.add_row(*[str(r.get(c,"")) for c in cols])
    console.print(t)

def _ensure_backend():
    try:
        with httpx.Client(base_url=BASE, timeout=3, headers=_headers()) as c:
            r=c.get("/health")
            if r.status_code==200:
                return True
    except Exception:
        pass
    console.print("[yellow]后端未启动 127.0.0.1:8000[/yellow] [dim]启动: cd apps/server; py -m uvicorn app.main:app --host 127.0.0.1 --port 8000[/dim]")
    return False

def _chat_loop():
    console.print("[bold cyan]Studying Planner[/bold cyan] [dim]v0.3 双轨·6节点·SSE[/dim]")
    console.print("[dim]直接输入目标回车规划，/help 看指令，/exit 退出[/dim]")
    # 启动时探活
    _ensure_backend()
    while True:
        try:
            inp = console.input("[bold green]❯[/bold green] ")
            # PowerShell 管道会带 BOM \ufeff，需显式去除
            inp = inp.lstrip("\ufeff").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]退出[/yellow]")
            break
        if not inp:
            continue
        low = inp.lstrip("\ufeff").lower().strip()
        if low in ("/exit", "/quit", "exit", "quit", "/q", ":q"):
            console.print("[yellow]再见![/yellow]")
            break
        if low in ("/help", "/h", "help", "?"):
            console.print("[cyan]/help[/cyan] 帮助  [cyan]/health[/cyan] 探活  [cyan]/trace <id>[/cyan]  [cyan]/graph <id>[/cyan]  [cyan]/stream <id>[/cyan]  [cyan]/clear[/cyan] 清屏  [cyan]/agent[/cyan] 清单  [cyan]/project[/cyan] 规划")
            console.print("[dim]示例: 30天过六级，每天2小时 | /agent 查清单 | /project --goal 1 --hours 2[/dim]")
            continue
        if low in ("/clear", "/cls", "clear"):
            try: console.clear()
            except: pass
            continue
        if low.startswith("/health"):
            health(json_out=False)
            continue
        if low.startswith("/trace"):
            parts=inp.split(maxsplit=1)
            tid=parts[1].strip() if len(parts)>1 else ""
            if tid:
                trace(trace_id=tid, goal=1, json_out=False)
            else:
                console.print("[yellow]用法: /trace <trace_id>[/yellow]")
            continue
        if low.startswith("/plan"):
            parts=inp.split()
            gid=1
            try:
                for i,p in enumerate(parts):
                    if p=="--goal" and i+1 < len(parts): gid=int(parts[i+1])
            except: pass
            plan(goal=gid, hours=2, mode="multi", json_out=False)
            continue
        if low.startswith("/agent"):
            agent_manifest(json_out=False)
            continue
        if low.startswith("/project"):
            parts=inp.split()
            gid=1
            hours=2
            try:
                for i,p in enumerate(parts):
                    if p=="--goal" and i+1 < len(parts): gid=int(parts[i+1])
                    if p=="--hours" and i+1 < len(parts): hours=int(parts[i+1])
                    if p=="--hour" and i+1 < len(parts): hours=int(parts[i+1])
            except: pass
            project_plan(goal=gid, hours=hours, json_out=False)
            continue
        # 默认当作目标描述直接规划
        # 解析天数与科目，复用 WorkbenchView 逻辑
        import datetime as _dt
        text=inp
        subject="英语" if "英语" in text else "数据结构" if "数据结构" in text else None
        m=None
        import re as _re
        dm=_re.search(r"(\d+)\s*天", text)
        days=int(dm.group(1)) if dm else 7
        deadline=(_dt.datetime.now(_dt.timezone.utc)+_dt.timedelta(days=days)).isoformat()
        # 创建目标
        try:
            with _client() as c:
                # 健康检查
                if not _ensure_backend():
                    continue
                console.print(f"[dim]创建目标: {text[:30]}...[/dim]")
                r=c.post("/api/v1/goals", json={"title": text[:30], "description": text, "deadline": deadline, "subject": subject, "status":"active"})
                if r.status_code not in (200,201):
                    console.print(f"[red]创建目标失败 {r.status_code}[/red] {r.text[:300]}")
                    continue
                gid=r.json()["data"]["id"]
                console.print(f"[green]目标 #{gid} 已创建，正在6节点规划...[/green] [dim](planner→researcher→executor→critic→mentor→reflector)[/dim]")
                # 规划
                import time as _time
                t0=_time.time()
                # 用长超时
                with httpx.Client(base_url=BASE, timeout=60, headers=_headers()) as c2:
                    r2=c2.post(f"/api/v1/plans?mode=multi", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
                if r2.status_code!=200:
                    console.print(f"[red]规划失败 {r2.status_code}[/red] {r2.text[:500]}")
                    continue
                data=r2.json().get("data",r2.json())
                tid=data.get("trace_id")
                tasks=data.get("tasks",[])
                # 兜底：若 tasks 为空或标题缺失，从 logs 取真实任务
                if not tasks or not any(isinstance(t, dict) and t.get("title") for t in tasks):
                    try:
                        rl=c.get(f"/api/v1/plans/{tid}/logs")
                        if rl.status_code==200:
                            logs=rl.json().get("data",[])
                            if logs and isinstance(logs[0].get("output"), dict):
                                tasks=logs[0]["output"].get("tasks", tasks)
                    except Exception:
                        pass
                console.print(f"[bold green]✓ 规划完成 trace={tid[:8] if tid else '?'} {len(tasks)}任务 rewrites={data.get('rewrites',0)}[/bold green] [dim]{_time.time()-t0:.1f}s[/dim]")
                if tasks:
                    for t in tasks[:6]:
                        title=t.get("title","") if isinstance(t, dict) else str(getattr(t,"title",""))
                        ps=t.get("planned_start","")[:16] if isinstance(t, dict) else ""
                        if not title:
                            title="(任务)"
                        console.print(f"  [cyan]•[/cyan] {title} [dim]{ps}[/dim]")
                    if len(tasks)>6:
                        console.print(f"  [dim]...还有{len(tasks)-6}个[/dim]")
                console.print(f"[dim]查看: trace {tid[:8] if tid else '?'} | graph-state {tid[:8] if tid else '?'} | stream {tid[:8] if tid else '?'}[/dim]")
                if tid:
                    console.print(f"[dim]提示: /trace {tid} 看全量 logs[/dim]")
        except Exception as e:
            console.print(f"[red]异常 {e}[/red]")
            import traceback as _tb; console.print(f"[dim]{_tb.format_exc()[:600]}[/dim]")

@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        # 无参直接进入对话
        _chat_loop()

@app.command()
def trace(goal:int=typer.Option(1,help="goal_id"), trace_id:str=typer.Option(None,help="trace_id 优先"), json_out:bool=typer.Option(False,"--json",help="JSON输出")):
    """查看某目标的最近规划轨迹（可追溯 trace_id→logs→SSE→graph→inspector）"""
    with _client() as c:
        if trace_id:
            r=c.get(f"/api/v1/plans/{trace_id}/logs")
            if r.status_code!=200:
                console.print(f"[red]trace {trace_id} 不存在[/red]")
                if json_out: console.print_json(json.dumps({"error":"not found","trace_id":trace_id}))
                raise typer.Exit(1)
            logs=r.json().get("data",[])
            _print({"trace_id":trace_id,"logs":logs,"count":len(logs)}, json_out, f"Trace {trace_id}")
            if not json_out and isinstance(logs, list):
                _table([{"agent":l.get("agent_name"),"tools":len(l.get("tool_calls") or []),"trace":str(l.get("trace_id",""))[:8]} for l in logs[:8]],["agent","tools","trace"],"Agent 轨迹")
            # Inspector 与 Graph 快照（复用 /plans/{trace_id}/inspector & /graph）
            try:
                ri=c.get(f"/api/v1/plans/{trace_id}/inspector")
                if ri.status_code==200:
                    insp=ri.json().get("data",{})
                    _print({"inspector_state": insp.get("state",{}), "patch": insp.get("patch",{})}, json_out, f"Inspector {trace_id}")
                rg=c.get(f"/api/v1/plans/{trace_id}/graph")
                if rg.status_code==200:
                    g=rg.json().get("data",{})
                    _print({"graph": g}, json_out, f"Graph {trace_id}")
                    if not json_out and isinstance(g, dict):
                        nodes=g.get("nodes",[])[:6]; edges=g.get("edges",[])[:6]
                        if nodes: _table([{"id":n.get("id"),"name":n.get("name"),"status":n.get("status")} for n in nodes],["id","name","status"],"Graph 节点")
                        if edges: _table([{"from":e.get("from"),"to":e.get("to"),"type":e.get("type") or e.get("relation")} for e in edges],["from","to","type"],"Graph 边")
                es=c.get(f"/api/v1/plans/stream?trace_id={trace_id}", headers={"Accept":"text/event-stream"})
                if es.status_code==200: console.print(f"[dim]SSE: {BASE}/api/v1/plans/stream?trace_id={trace_id} (id/retry 带 Last-Event-ID)[/dim]")
            except Exception as e:
                if not json_out: console.print(f"[yellow]inspector/graph/stream 失败 {e}[/yellow]")
            return
        r=c.get(f"/api/v1/goals/{goal}")
        if r.status_code!=200:
            console.print(f"[red]goal {goal} 不存在[/red]")
            if json_out: console.print_json(json.dumps({"error":"goal not found","goal_id":goal}))
            raise typer.Exit(1)
        g=r.json(); r2=c.get(f"/api/v1/tasks?goal_id={goal}&page=1&size=5"); t=r2.json() if r2.status_code==200 else {}
        _print({"goal":g.get("data"),"tasks":t.get("data",{}),"hint":"use plan to generate trace_id"}, json_out, f"Goal {goal} 轨迹")
        if not json_out:
            items=t.get("data",{}).get("items",[]) if isinstance(t.get("data"),dict) else []
            if items: _table(items[:5],["id","title","status","planned_start"],"最近任务")

@app.command()
def plan(goal:int=typer.Option(1,help="goal_id"), hours:int=typer.Option(2,help="1-8"), mode:str=typer.Option("multi",help="multi|single"), json_out:bool=typer.Option(False,"--json")):
    """触发规划并返回 trace_id 与可追溯日志（POST /plans → logs → SSE）"""
    with _client() as c:
        r=c.post(f"/api/v1/plans?mode={mode}", json={"goal_id":goal,"preferences":{"hours_per_day":hours}})
        if r.status_code!=200:
            console.print(f"[red]plan 失败 {r.status_code}[/red] {r.text[:200]}")
            if json_out: console.print_json(json.dumps({"error":r.text}))
            raise typer.Exit(1)
        data=r.json().get("data",r.json()); tid=data.get("trace_id")
        _print(data, json_out, f"Plan trace={tid}")
        if tid and not json_out:
            try:
                r2=c.get(f"/api/v1/plans/{tid}/logs")
                if r2.status_code==200:
                    logs=r2.json().get("data",[]); console.print(f"[green]可追溯日志 {len(logs)} 条[/green] [dim]/api/v1/plans/{tid}/logs[/dim]")
                    _table([{"agent":l.get("agent_name"),"trace":l.get("trace_id")[:8]} for l in logs[:6]],["agent","trace"],"Agent 轨迹")
                    console.print(f"[dim]SSE: curl -N {BASE}/api/v1/plans/stream?trace_id={tid}[/dim]")
            except Exception as e: console.print(f"[yellow]logs 失败 {e}[/yellow]")

@app.command()
def graph(query:str=typer.Option("链表",help="关键词"), subject:str=typer.Option(None,help="学科"), top_k:int=typer.Option(5), json_out:bool=typer.Option(False,"--json")):
    """知识图谱溯源：PREREQ 前置依赖（复用 /graph + evidence）"""
    with _client() as c:
        params={"keyword":query,"limit":top_k}
        if subject: params["subject"]=subject
        r=c.get("/api/v1/graph", params=params)
        if r.status_code!=200:
            r2=c.get("/api/v1/experiments/graph-evidence", params={"query":query,"subject":subject or ""})
            data=r2.json().get("data",r2.json()) if r2.status_code==200 else {"error":r.text}
            _print(data, json_out, f"Graph evidence {query}"); return
        data=r.json().get("data",r.json()); _print(data, json_out, f"Graph {query}")
        if not json_out and isinstance(data,dict):
            nodes=data.get("nodes",[])[:5]; edges=data.get("edges",[])[:5]
            if nodes: _table([{"name":n.get("name"),"id":n.get("id")} for n in nodes],["name","id"],"节点")
            if edges: _table([{"from":e.get("from"),"to":e.get("to"),"rel":e.get("relation")} for e in edges],["from","to","rel"],"PREREQ")

@app.command()
def memory(query:str=typer.Option("学习"), top_k:int=typer.Option(5), with_ablation:bool=typer.Option(False,"--ablation",help="有/无对照"), json_out:bool=typer.Option(False,"--json")):
    """记忆溯源：pgvector 召回与有/无对照（复用 /memory/search + memory-ablation）"""
    with _client() as c:
        r=c.get("/api/v1/memory/search", params={"q":query,"top_k":top_k})
        if r.status_code!=200:
            r=c.get("/api/v1/experiments/memory-ablation", params={"query":query,"top_k":top_k})
            data=r.json().get("data",r.json()) if r.status_code==200 else {"error":r.text}
            _print(data, json_out, f"Memory ablation {query}"); return
        data=r.json().get("data",r.json()); _print(data, json_out, f"Memory {query}")
        if with_ablation:
            r2=c.get("/api/v1/experiments/memory-ablation", params={"query":query,"top_k":top_k})
            if r2.status_code==200:
                ab=r2.json().get("data",{}); _print(ab, json_out, "记忆消融对照")
                if not json_out: console.print(f"[green]Delta={ab.get('delta')} 提升 {ab.get('improvement')}[/green]")
        if not json_out and isinstance(data,dict):
            items=data.get("items",data.get("results",[])) if isinstance(data,dict) else []
            if isinstance(items,list) and items:
                preview=[{"id":str(it.get("id",""))[:8],"score":it.get("score",""),"text":str(it.get("content",it.get("text","")))[:40]} for it in items[:5]]
                _table(preview,["id","score","text"],"TopK")

@app.command()
def health(json_out:bool=typer.Option(False,"--json")):
    """探针：/health + /api/v1/health（sidecar 健康）"""
    with _client() as c:
        r=c.get("/health"); _print(r.json() if r.status_code==200 else {"error":r.text}, json_out, "Root /health")
        r2=c.get("/api/v1/health"); _print(r2.json() if r2.status_code==200 else {"error":r2.text}, json_out, "API /api/v1/health")

@app.command()
def inspector(trace_id:str=typer.Argument(..., help="trace_id"), json_out:bool=typer.Option(False,"--json")):
    """Inspector：查看 trace 的状态快照与 patch（GET /plans/{trace_id}/inspector）"""
    with _client() as c:
        r=c.get(f"/api/v1/plans/{trace_id}/inspector")
        if r.status_code!=200:
            console.print(f"[red]inspector {trace_id} 不存在 {r.status_code}[/red] {r.text[:200]}")
            raise typer.Exit(1)
        data=r.json().get("data",r.json()); _print(data, json_out, f"Inspector {trace_id}")
        if not json_out and isinstance(data, dict):
            state=data.get("state",{}); logs=data.get("logs",[])
            if state: console.print(f"[green]state keys: {', '.join(list(state.keys())[:8])}[/green]")
            if logs: _table([{"agent":l.get("agent_name"),"id":str(l.get("id",""))[:6]} for l in logs[:6]],["agent","id"],"Logs")

@app.command()
def graph_state(trace_id:str=typer.Argument(..., help="trace_id"), json_out:bool=typer.Option(False,"--json")):
    """Graph：查看 trace 的 DAG 状态（GET /plans/{trace_id}/graph）"""
    with _client() as c:
        r=c.get(f"/api/v1/plans/{trace_id}/graph")
        if r.status_code!=200:
            console.print(f"[red]graph {trace_id} 不存在 {r.status_code}[/red] {r.text[:200]}")
            raise typer.Exit(1)
        data=r.json().get("data",r.json()); _print(data, json_out, f"Graph {trace_id}")
        if not json_out and isinstance(data, dict):
            nodes=data.get("nodes",[])[:8]; edges=data.get("edges",[])[:8]
            if nodes: _table([{"id":n.get("id"),"status":n.get("status")} for n in nodes],["id","status"],"Graph 节点")
            if edges: _table([{"from":e.get("from"),"to":e.get("to"),"type":e.get("type")} for e in edges],["from","to","type"],"Graph 边")
            console.print(f"[dim]status={data.get('status')} rewrites={data.get('rewrites')}[/dim]")

@app.command()
def stream(trace_id:str=typer.Argument(..., help="trace_id"), last_event_id:str=typer.Option(None, help="断点续传 Last-Event-ID"), json_out:bool=typer.Option(False,"--json")):
    """SSE 流式：实时消费 /plans/stream（支持 Last-Event-ID 续播）"""
    import time
    headers={"Accept":"text/event-stream"}
    if last_event_id: headers["Last-Event-ID"]=last_event_id
    # Typer+Rich 逐行打印 SSE
    url=f"{BASE}/api/v1/plans/stream?trace_id={trace_id}"
    if last_event_id: url += f"&last_event_id={last_event_id}"
    console.print(f"[cyan]SSE GET {url} 带 id/retry ...[/cyan]")
    try:
        with httpx.stream("GET", url, headers=_headers(headers), timeout=30, follow_redirects=True) as r:
            if r.status_code!=200:
                console.print(f"[red]stream 失败 {r.status_code}[/red] {r.read().decode()[:200]}")
                raise typer.Exit(1)
            for line in r.iter_lines():
                if not line: continue
                if line.startswith("id:"): console.print(f"[dim]{line}[/dim]")
                elif line.startswith("event:"): console.print(f"[bold magenta]{line}[/bold magenta]")
                elif line.startswith("data:"):
                    payload=line[5:].strip()
                    try: obj=json.loads(payload); console.print(JSON.from_data(obj))
                    except: console.print(payload)
                    if json_out: console.print_json(payload)
                elif line.startswith("retry:"): console.print(f"[dim]{line}[/dim]")
    except KeyboardInterrupt:
        console.print("[yellow]中断[/yellow]")
    except Exception as e:
        console.print(f"[red]stream 异常 {e}[/red]")
        raise typer.Exit(1)

@app.command(name="plans")
def plans_alias(goal:int=typer.Option(1), json_out:bool=typer.Option(False,"--json")):
    """别名：兼容旧 plans"""
    return plan(goal=goal, json_out=json_out)

@app.command(name="planner")
def planner_alias(goal:int=typer.Option(1,help="goal_id"), hours:int=typer.Option(2,help="1-8"), mode:str=typer.Option("multi",help="multi|single"), json_out:bool=typer.Option(False,"--json")):
    """别名：studying planner 即 plan"""
    return plan(goal=goal, hours=hours, mode=mode, json_out=json_out)

@app.command(name="agent")
def agent_manifest(json_out:bool=typer.Option(False,"--json",help="JSON输出")):
    """SystemAgent 清单：GET /api/v1/agent/manifest 展示 name/tools/sub_agents"""
    with _client() as c:
        r=c.get("/api/v1/agent/manifest")
        if r.status_code!=200:
            console.print(f"[red]agent manifest 失败 {r.status_code}[/red] {r.text[:200]}")
            if json_out: console.print_json(json.dumps({"error":r.text}))
            raise typer.Exit(1)
        payload=r.json()
        data=payload.get("data",payload)
        _print(data, json_out, "SystemAgent Manifest")
        if not json_out and isinstance(data, dict):
            tools=data.get("tools",[])
            sub_agents=data.get("sub_agents",[])
            # 满足任务：name/version/tools/sub_agents 表格
            summary=[{"name":data.get("name",""),"version":data.get("version",""),"tools":str(len(tools)) if isinstance(tools,list) else str(tools),"sub_agents":", ".join(sub_agents) if isinstance(sub_agents,list) else str(sub_agents)}]
            _table(summary,["name","version","tools","sub_agents"],"Agent 概览")
            if isinstance(tools,list) and tools:
                rows=[]
                for t in tools[:10]:
                    if isinstance(t, dict):
                        rows.append({"name":t.get("name",""),"label":t.get("label",""),"description":str(t.get("description",""))[:40]})
                    else:
                        rows.append({"name":str(t),"label":"","description":""})
                _table(rows,["name","label","description"],"Tools")
                if len(tools)>10:
                    console.print(f"[dim]...还有{len(tools)-10}个工具[/dim]")
            if isinstance(sub_agents,list) and sub_agents:
                _table([{"sub_agent":s} for s in sub_agents],["sub_agent"],"Sub Agents")
            console.print(f"[dim]entry={data.get('entry','')} stream={data.get('stream','')} graph={data.get('graph','')}[/dim]")

@app.command(name="project")
def project_plan(goal:int=typer.Option(1,help="goal_id"), hours:int=typer.Option(2,help="1-8"), json_out:bool=typer.Option(False,"--json",help="JSON输出")):
    """项目规划：通过 SystemAgent ainvoke 触发6节点规划 (POST /api/v1/plans) 并可追溯"""
    console.print("[dim]SystemAgent ainvoke 触发中... 内部 6子Agent协作 (planner→researcher→executor→critic→mentor→reflector)[/dim]")
    with _client() as c:
        # 1) 先拉 manifest 发现 SystemAgent 能力（任务要求：GET /agent/manifest 后 POST /agent/plan）
        try:
            mr=c.get("/api/v1/agent/manifest")
            if mr.status_code==200:
                mdata=mr.json().get("data", mr.json())
                tcnt=len(mdata.get("tools",[])) if isinstance(mdata.get("tools"), list) else mdata.get("tools","?")
                sacnt=len(mdata.get("sub_agents",[])) if isinstance(mdata.get("sub_agents"), list) else 0
                console.print(f"[dim]发现 SystemAgent {mdata.get('name','')} v{mdata.get('version','')} 工具{tcnt} 子智能体{sacnt}[/dim]")
            else:
                console.print(f"[yellow]agent manifest 异常 {mr.status_code} 仍尝试规划[/yellow]")
        except Exception as e:
            console.print(f"[yellow]manifest 获取失败 {e} 仍尝试规划[/yellow]")
        r=None
        # 2) 优先尝试专用端点 /api/v1/agent/plan，若不存在则回退复用现有 /api/v1/plans
        # 使用长超时（60s）避免 LangGraph 6节点协作超时（实测 31s）
        try:
            r_try=c.post("/api/v1/agent/plan", json={"goal_id":goal,"preferences":{"hours_per_day":hours}}, timeout=60)
            if r_try.status_code not in (404, 405):
                r=r_try
            else:
                console.print(f"[dim]回退 /api/v1/plans?mode=multi （/agent/plan {r_try.status_code}）[/dim]")
        except Exception as e:
            console.print(f"[yellow]/agent/plan 异常 {e} 回退 /plans[/yellow]")
            r=None
        if r is None:
            try:
                r=c.post(f"/api/v1/plans?mode=multi", json={"goal_id":goal,"preferences":{"hours_per_day":hours}}, timeout=60)
            except Exception as e:
                console.print(f"[red]project 规划异常 {e}[/red]")
                raise typer.Exit(1)
        if r.status_code!=200:
            console.print(f"[red]project 规划失败 {r.status_code}[/red] {r.text[:500]}")
            if json_out: console.print_json(json.dumps({"error":r.text}))
            raise typer.Exit(1)
        data=r.json().get("data",r.json())
        tid=data.get("trace_id")
        _print(data, json_out, f"Project trace={tid}")
        if tid and not json_out:
            console.print(f"[green]✓ SystemAgent 规划完成 trace={tid}[/green] [dim]rewrites={data.get('rewrites',0)}[/dim]")
            console.print(f"[dim]查看: studying trace --trace-id {tid}[/dim]")
            console.print(f"[dim]提示: studying trace --trace-id {tid} 或  /trace {tid}  |  studying stream {tid}[/dim]")
            # 提示 studying trace 快速查看
            console.print(f"[bold cyan]提示: studying trace --trace-id {tid}[/bold cyan] [dim]或 studying trace --goal {goal}[/dim]")
            try:
                r2=c.get(f"/api/v1/plans/{tid}/logs")
                if r2.status_code==200:
                    logs=r2.json().get("data",[])
                    console.print(f"[green]可追溯日志 {len(logs)} 条[/green] [dim]/api/v1/plans/{tid}/logs[/dim]")
                    console.print(f"[dim]SSE: {BASE}/api/v1/plans/stream?trace_id={tid}[/dim]")
            except Exception:
                pass

def main():
    """Entry for console_scripts studying."""
    app()

if __name__=="__main__": main()
