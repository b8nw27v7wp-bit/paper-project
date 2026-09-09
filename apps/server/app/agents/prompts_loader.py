import pathlib


def load_layered_agents_md(cwd: str | pathlib.Path | None = None, max_bytes: int = 6000) -> str:
    """分层 AGENTS.md（对标 Codex agents_md.rs）。

    自 cwd 向上到仓根收集 AGENTS.md，拼接+来源标注+字节预算，缺失返回""。
    - 仓根判定：最近的含 .git 或 mcp.json 的祖先（含自身）；找不到则到文件系统根。
    - 拼接顺序：仓根在前、cwd 在后（越具体越靠后），每段前加 `# source: <abs path>` 标注。
    - 字节预算：按 UTF-8 字节累计截断到 max_bytes，超出部分截断并追加 `[truncated: byte budget N]`。
    - 原 load_prompt/substitute 不动。
    """
    try:
        start = pathlib.Path(cwd).resolve() if cwd is not None else pathlib.Path.cwd().resolve()
    except Exception:
        return ""
    try:
        if start.is_file():
            start = start.parent
    except Exception:
        return ""
    # 找仓根
    repo_root: pathlib.Path | None = None
    try:
        candidates = [start, *start.parents]
        for p in candidates:
            try:
                if (p / ".git").exists() or (p / "mcp.json").exists():
                    repo_root = p
                    break
            except OSError:
                continue
    except Exception:
        repo_root = None
    # 收集链：cwd -> ... -> 仓根（或文件系统根），上限 32 层防环
    chain: list[pathlib.Path] = []
    try:
        cur = start
        for _ in range(33):
            chain.append(cur / "AGENTS.md")
            if repo_root is not None and cur == repo_root:
                break
            if cur.parent == cur:
                break
            cur = cur.parent
        # 反转为仓根->cwd
        chain = list(reversed(chain))
    except Exception:
        return ""
    parts: list[str] = []
    total = 0
    try:
        for fp in chain:
            try:
                if not fp.is_file():
                    continue
                text = fp.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            chunk = f"# source: {fp}\n{text.strip()}\n" if text.strip() else f"# source: {fp}\n"
            raw = chunk.encode("utf-8")
            if total + len(raw) <= max_bytes:
                parts.append(chunk.rstrip() + "\n")
                total += len(raw)
                continue
            # 预算不足：截断本段以填满预算
            remaining = max_bytes - total
            if remaining <= 0:
                break
            truncated = raw[:remaining].decode("utf-8", errors="ignore")
            parts.append(truncated)
            total = max_bytes
            parts.append("\n...[truncated: byte budget %d]\n" % max_bytes)
            break
        if not parts:
            return ""
        out = "\n---\n".join(p.rstrip() for p in parts).strip() + "\n"
        # 最终保险：按字节再截一次
        encoded = out.encode("utf-8")
        if len(encoded) > max_bytes + 256:  # 允许截断标记略超
            out = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return out
    except Exception:
        return ""


def load_prompt(name: str) -> str:
    p = pathlib.Path(f"prompts/{name}.md")
    if not p.exists():
        p = pathlib.Path(f"E:/paper project/prompts/{name}.md")
    try:
        text = p.read_text(encoding="utf-8")
        # 去掉 frontmatter
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                return text[end+4:].strip()
        return text.strip()
    except (OSError, UnicodeDecodeError):
        return ""

def substitute(template: str, *args: str) -> str:
    # Pi式 $1 $2 $@
    res = template
    for i, a in enumerate(args, 1):
        res = res.replace(f"${i}", a)
    res = res.replace("$@", " ".join(args))
    res = res.replace("$ARGUMENTS", " ".join(args))
    return res
