"""
W14-16 Neo4j 万节点多跳压测（SQLite 回退等价）
- 目标：1万节点 + 5万边 + BFS 2层检索 P95 <500ms
- 回退：SQLite graph.db 上执行，Neo4j 时走 neo.py
"""
import time, random, statistics, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph.sqlite_graph import _get_conn, _init_db, sqlite_clear, sqlite_get_graph, sqlite_search_prereqs

def bench(n_nodes=10000, n_edges=50000, n_query=50):
    print(f"[graph-bench] init {n_nodes} nodes / {n_edges} edges")
    _init_db()
    sqlite_clear()
    conn=_get_conn()
    try:
        cur=conn.cursor()
        t0=time.time()
        # 批量节点
        batch=1000
        for i in range(0, n_nodes, batch):
            rows=[(f"节点{i+j}", random.choice(["计算机","数学","英语","物理"])) for j in range(min(batch, n_nodes-i))]
            cur.executemany("INSERT OR IGNORE INTO knowledge_nodes (name, subject) VALUES (?,?)", rows)
            conn.commit()
        print(f"[graph-bench] nodes inserted in {time.time()-t0:.2f}s")
        # 批量边：随机连
        t0=time.time()
        edges=set()
        while len(edges) < n_edges:
            a=random.randint(0, n_nodes-1)
            b=random.randint(0, n_nodes-1)
            if a==b: continue
            frm=f"节点{a}"; to=f"节点{b}"
            if (frm,to) in edges: continue
            edges.add((frm,to))
            if len(edges)%10000==0:
                print(f"[graph-bench] edges {len(edges)}/{n_edges}")
        # 批量插入
        batch_edges=list(edges)
        for i in range(0, len(batch_edges), batch):
            chunk=batch_edges[i:i+batch]
            cur.executemany("INSERT OR IGNORE INTO knowledge_edges (from_node,to_node,type) VALUES (?,?,?)", [(f,t,"PREREQUISITE") for f,t in chunk])
            conn.commit()
        print(f"[graph-bench] edges inserted in {time.time()-t0:.2f}s")
    finally:
        conn.close()
    # 查询压测：BFS 2层
    lat=[]
    for qi in range(n_query):
        kw=f"节点{random.randint(0, n_nodes-1)}"
        t1=time.perf_counter()
        res=sqlite_search_prereqs(kw, depth=2)
        lat.append((time.perf_counter()-t1)*1000)
        if qi%10==0:
            print(f"[graph-bench] query {qi} kw={kw} -> {len(res)} edges in {lat[-1]:.1f}ms")
    p50=statistics.median(lat); p95=sorted(lat)[int(len(lat)*0.95)]; p99=sorted(lat)[int(len(lat)*0.99)]; avg=sum(lat)/len(lat)
    print(f"[graph-bench] query {n_query} BFS depth2 over {n_nodes} nodes/{n_edges} edges: p50 {p50:.1f}ms p95 {p95:.1f}ms p99 {p99:.1f}ms avg {avg:.1f}ms")
    ok=p95 < 500
    print(f"[graph-bench] {'PASS' if ok else 'NEEDS_TUNE'} p95<500ms ? {p95:.1f} < 500")
    # 清理后恢复空
    # sqlite_clear()  # 保留数据供后续检索验证，或清掉
    return {"p50":p50,"p95":p95,"p99":p99,"avg":avg,"ok":ok}

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=10000)
    ap.add_argument("--edges", type=int, default=50000)
    ap.add_argument("--q", type=int, default=50)
    args=ap.parse_args()
    bench(n_nodes=args.nodes, n_edges=args.edges, n_query=args.q)
