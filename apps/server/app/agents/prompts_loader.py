import pathlib

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
    except Exception:
        return ""

def substitute(template: str, *args: str) -> str:
    # Pi式 $1 $2 $@
    res = template
    for i, a in enumerate(args, 1):
        res = res.replace(f"${i}", a)
    res = res.replace("$@", " ".join(args))
    res = res.replace("$ARGUMENTS", " ".join(args))
    return res
