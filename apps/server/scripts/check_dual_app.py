"""双份 app/ 一致性门禁：根 app/ vs apps/server/app/ 必须字节级一致。

用法（仓库根或 apps/server 均可）：
    py apps/server/scripts/check_dual_app.py
非 0 diff 即 exit 1，并打印差异文件清单。
约束来源：00-管理/遗留项执行计划-L1-L12-20260905.md §0 双份同步要求。
"""
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
A = ROOT / "app"
B = ROOT / "apps" / "server" / "app"

SKIP_DIRS = {"__pycache__", ".ruff_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def collect(base: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix in SKIP_SUFFIX:
            continue
        out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    if not A.is_dir() or not B.is_dir():
        print(f"missing dir: {A} / {B}")
        return 1
    fa, fb = collect(A), collect(B)
    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    diff = sorted(f for f in set(fa) & set(fb) if fa[f] != fb[f])
    print(f"root app/: {len(fa)} files; apps/server/app/: {len(fb)} files")
    ok = True
    if only_a:
        ok = False
        print(f"only in root app/ ({len(only_a)}): {only_a[:20]}")
    if only_b:
        ok = False
        print(f"only in apps/server/app/ ({len(only_b)}): {only_b[:20]}")
    if diff:
        ok = False
        print(f"content diff ({len(diff)}):")
        for f in diff[:30]:
            print(f"  DIFF: {f}")
    if ok:
        print("dual-app guard: 0 diff PASS")
        return 0
    print("dual-app guard: FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
