#!/usr/bin/env python3
"""列出当前环境已安装的全部 skill（名称 + 简介 + 来源 + 路径）。

用途：回答"你能做什么 / 有哪些技能"这类问题时，用真实扫描结果作答，避免凭记忆编造。

用法：
    python list_skills.py                 输出分组文本
    python list_skills.py --format json  输出 JSON
    python list_skills.py --keyword 表格  按名称或简介过滤
"""

import argparse
import json
import os
import re
import sys

# 业务白名单：只保留与钉钉、日常业务直接相关的技能。
# 默认只输出这些；需要全量时用 --scope all。
BUSINESS = [
    "binkang-daily-report",
    "dingtalk-robot-publish",
    "dws",
]


def _expanduser_rel(p):
    """支持 ~ 开头的路径；含 .. 时先按字面拼接再规范化。"""
    if p.startswith("~"):
        p = os.path.expanduser("~") + p[1:]
    return os.path.normpath(p)


DEFAULT_ROOTS = [
    ("用户自建", "~/.workbuddy/skills"),
    ("连接器", "~/.workbuddy/connectors/skills"),
    ("插件市场", "~/.workbuddy/plugins/cache"),
    ("内置", "D:/Company/Softwares/WorkBuddy/resources/app.asar.unpacked/"
             "resources/plugins/workbuddy-builtin/skills"),
    ("内置", "C:/Company/Softwares/WorkBuddy/resources/app.asar.unpacked/"
             "resources/plugins/workbuddy-builtin/skills"),
]

# 分组展示顺序；未列出的分组排在最后
ORDER = ["用户自建", "连接器", "内置", "插件市场"]


def roots():
    out = [(c, _expanduser_rel(p)) for c, p in DEFAULT_ROOTS]
    extra = os.environ.get("WORKBUDDY_SKILL_ROOTS", "")
    for item in extra.split(os.pathsep):
        if not item.strip():
            continue
        if ":" in item[1:3] or "=" in item:
            cat, _, p = item.partition("=")
        else:
            cat, p = "自定义", item
        out.append((cat.strip() or "自定义", _expanduser_rel(p.strip())))
    return out


MAX_DEPTH = 6
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "references", "scripts", "templates"}


def parse_frontmatter(path):
    """读取 SKILL.md 的 YAML frontmatter，返回 dict。只做扁平 key: value，够用即可。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(8192)
    except OSError:
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---", head, re.S)
    if not m:
        return {}
    body = m.group(1)
    out, key = {}, None
    for line in body.split("\n"):
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            out[key] = kv.group(2).strip()
        elif key and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def clean(s):
    """去掉 YAML 块标量指示符与多余空白，得到单行纯文本。"""
    s = (s or "").strip()
    s = re.sub(r"^[|>][-+]?\s*", "", s)
    s = re.sub(r"^[|>][-+]?$", "", s).strip()
    return re.sub(r"\s+", " ", s).strip().strip('"\'')


def scan():
    found, seen = [], set()
    for category, root in roots():
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
            if depth > MAX_DEPTH:
                dirnames[:] = []
                continue
            if "SKILL.md" not in filenames:
                continue
            p = os.path.join(dirpath, "SKILL.md")
            p = os.path.normpath(p)
            if p in seen:
                continue
            seen.add(p)
            meta = parse_frontmatter(p)
            name = clean(meta.get("name")) or os.path.basename(dirpath)
            found.append({
                "name": name,
                "description": clean(meta.get("description")),
                "category": category,
                "path": p,
            })
    def rank(x):
        try:
            c = ORDER.index(x["category"])
        except ValueError:
            c = len(ORDER)
        return (c, x["name"].lower())

    found.sort(key=rank)
    dedup, seen_name = [], set()
    for i in found:
        k = i["name"].lower()
        if k in seen_name:
            continue
        seen_name.add(k)
        dedup.append(i)
    return dedup


EN_LEAD = re.compile(
    r"^(use this skill|use when|helps? users?|this skill|use it|load this skill)"
    r"[^,;.]{0,60}[,;.]\s*", re.I)


def note(s, limit=40):
    """把 description 压成一句话短注：去引导语、取首个分句、按词/字边界截断。"""
    s = clean(s)
    if not s:
        return ""
    prev = None
    while prev != s:
        prev = s
        s = EN_LEAD.sub("", s).strip()
    s = re.split(r"[。；;！!？?\n]", s)[0]
    s = re.sub(r"^(当|如果)?(用户|你)?(问|提到|要求|需要)[^，,]{0,12}[，,]", "", s)
    s = s.strip(" ，,。")
    if len(s) <= limit:
        return s
    cut = s[:limit]
    if re.fullmatch(r"[\x00-\x7f]*", cut):
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip(" ，,、") + "…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=["text", "brief", "json"], default="text")
    ap.add_argument("--scope", choices=["business", "all"], default="business",
                    help="business=仅钉钉与业务相关（默认）；all=全部已装技能")
    ap.add_argument("--keyword", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    items = scan()
    if a.scope == "business":
        allow = {n.lower() for n in BUSINESS}
        items = [i for i in items if i["name"].lower() in allow]
    if a.keyword:
        k = a.keyword.lower()
        items = [i for i in items
                 if k in i["name"].lower() or k in i["description"].lower()]
    if a.limit:
        items = items[:a.limit]

    if a.format == "json":
        print(json.dumps({"count": len(items), "skills": items},
                         ensure_ascii=False, indent=2))
        return

    if a.format == "brief":
        for n, i in enumerate(items, 1):
            nb = note(i["description"])
            print("%d. %s%s" % (n, i["name"], (" — " + nb) if nb else ""))
        return

    if not items:
        print("未匹配到任何 skill。")
        return
    cur = None
    for i in items:
        if i["category"] != cur:
            cur = i["category"]
            print("\n【%s】" % cur)
        d = i["description"]
        if len(d) > 90:
            d = d[:90] + "…"
        print("  · %s — %s" % (i["name"], d) if d else "  · %s" % i["name"])
    print("\n共 %d 个。" % len(items))


if __name__ == "__main__":
    sys.exit(main())
