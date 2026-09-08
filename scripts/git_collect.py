#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Git 仓库抓取提交并结构化输出。

用法:
  python git_collect.py <repo> [--days N] [--since ISO] [--until ISO] [--all]
        [--out file.json] [--save-diffs DIR] [--type all|bugfix]

- <repo> 可以是本地目录路径，也可以是 git 地址（自动克隆/拉取到缓存）。
- 默认抓取最近 1 天；--all 抓取全部；--since/--until 用 ISO 时间限定。
- 每条提交输出 commit_hash/title/author/commit_time/type/confidence/summary/files_changed/diff_stat。
- --save-diffs DIR 会把每个 Bug修复 提交的完整 diff 存成 <DIR>/<short>.patch，
  供 agent/LLM 读取 diff 来补充 现象/原因/解决方案。
"""
import argparse, json, os, re, subprocess, sys, tempfile, datetime, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import CONFIG_PATH  # noqa: E402

BUG_KEYS = ["fix", "bug", "hotfix", "resolve", "resolves #", "fixes #", "closes #",
            "correct", "repair", "patch", "workaround", "quickfix", "bugfix",
            "修复", "修正", "解决", "缺陷", "补丁", "故障", "问题修复"]
FEAT_KEYS = ["feat", "feature", "add", "implement", "new", "introduce",
             "新增", "添加", "实现", "需求", "开发", "功能", "支持"]
REFACTOR_KEYS = ["refactor", "重构"]
DOCS_KEYS = ["docs", "doc", "文档"]
TEST_KEYS = ["test", "测试", "单测", "用例"]
CHORE_KEYS = ["chore", "build", "ci", "merge", "release", "版本", "构建"]

_PREFIX_MAP = {
    "fix": "Bug修复", "bugfix": "Bug修复", "hotfix": "Bug修复", "patch": "Bug修复",
    "feat": "需求开发", "feature": "需求开发",
    "refactor": "重构", "docs": "文档", "test": "测试", "tests": "测试",
    "chore": "其他", "build": "其他", "ci": "其他", "merge": "其他", "release": "其他",
}


def classify(subject, body, files):
    s = (subject + " " + body).lower()
    m = re.match(r"^\s*([a-z]+)(\([^)]*\))?\s*:", subject.strip())
    prefix = m.group(1) if m else None
    if prefix in _PREFIX_MAP:
        return _PREFIX_MAP[prefix], 0.95, "prefix:" + prefix
    for k in BUG_KEYS:
        if k in s:
            for f in FEAT_KEYS:
                if f in s:
                    return "Bug修复", 0.6, "both:" + k
            return "Bug修复", 0.9, "keyword:" + k
    for k in FEAT_KEYS:
        if k in s:
            return "需求开发", 0.8, "keyword:" + k
    for k in REFACTOR_KEYS:
        if k in s:
            return "重构", 0.8, "keyword:" + k
    for k in DOCS_KEYS:
        if k in s:
            return "文档", 0.8, "keyword:" + k
    for k in TEST_KEYS:
        if k in s:
            return "测试", 0.8, "keyword:" + k
    for k in CHORE_KEYS:
        if k in s:
            return "其他", 0.8, "keyword:" + k
    return "其他", 0.3, "none"


def _run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def repo_display_name(repo):
    name = repo.rstrip("/\\")
    if "/" in name or "\\" in name:
        name = name.replace("\\", "/").rstrip("/").split("/")[-1]
    return re.sub(r"\.git$", "", name) or "repo"


def ensure_repo(repo):
    """返回本地仓库目录。目录路径直接用；URL 则克隆/拉取到缓存。"""
    if os.path.isdir(repo):
        return repo, repo_display_name(repo)
    cache_root = os.path.join(os.path.dirname(CONFIG_PATH), "cache")
    os.makedirs(cache_root, exist_ok=True)
    name = repo_display_name(repo)
    local = os.path.join(cache_root, name)
    if os.path.isdir(local) and os.path.isdir(os.path.join(local, ".git")):
        _run(["git", "-C", local, "pull", "--ff-only"], cwd=None)
    else:
        p = _run(["git", "clone", "--quiet", repo, local])
        if p.returncode != 0:
            raise RuntimeError(f"克隆失败: {repo}\n{p.stderr}")
    return local, name


def git_log(repo_dir, since, until, all_commits):
    base = ["git", "log", "--pretty=format:%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%b%x1e"]
    if not all_commits:
        if since:
            base += ["--since", since]
        if until:
            base += ["--until", until]
    p = _run(base, cwd=repo_dir)
    if p.returncode != 0:
        raise RuntimeError(f"git log 失败: {p.stderr}")
    return p.stdout


def parse_log(text):
    commits = []
    for rec in text.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\x1f")
        if len(parts) < 7:
            continue
        commits.append({
            "commit_hash": parts[0].strip(),
            "short_hash": parts[1].strip(),
            "author": parts[2].strip(),
            "email": parts[3].strip(),
            "commit_time": parts[4].strip(),
            "subject": parts[5].strip(),
            "body": parts[6].strip(),
        })
    return commits


def get_stat(repo_dir, commit_hash):
    p = _run(["git", "show", "--numstat", "--format=", commit_hash], cwd=repo_dir)
    files, insertions, deletions = [], 0, 0
    for line in p.stdout.splitlines():
        line = line.rstrip("\r")
        if not line:
            continue
        m = re.match(r"^(\d+|-)\t(\d+|-)\t(.+)$", line)
        if m:
            a, d, path = m.group(1), m.group(2), m.group(3)
            insertions += int(a) if a.isdigit() else 0
            deletions += int(d) if d.isdigit() else 0
            path = re.sub(r"^.*=> ", "", path)  # 处理 rename "old => new"
            files.append(path)
    return files, insertions, deletions


def get_diff(repo_dir, commit_hash):
    p = _run(["git", "show", "--format=fuller", commit_hash], cwd=repo_dir)
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description="抓取 Git 提交并分类")
    ap.add_argument("repo", help="仓库本地路径或 git 地址")
    ap.add_argument("--days", type=int, default=1, help="抓取最近 N 天（默认 1）")
    ap.add_argument("--since", help="起始时间 ISO，如 2026-03-24T00:00:00+08:00")
    ap.add_argument("--until", help="截止时间 ISO")
    ap.add_argument("--all", action="store_true", help="抓取全部提交")
    ap.add_argument("--type", choices=["all", "bugfix"], default="all")
    ap.add_argument("--out", help="输出 JSON 文件路径")
    ap.add_argument("--save-diffs", help="把 Bug修复 提交的 diff 存到此目录")
    args = ap.parse_args()

    repo_dir, name = ensure_repo(args.repo)
    since = args.since
    if not since and not args.all:
        since = (datetime.datetime.now(datetime.timezone.utc) -
                 datetime.timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = git_log(repo_dir, since, args.until, args.all)
    commits = parse_log(raw)

    records = []
    for c in commits:
        files, ins, dele = get_stat(repo_dir, c["commit_hash"])
        ctype, conf, reason = classify(c["subject"], c["body"], files)
        rec = {
            "commit_hash": c["commit_hash"],
            "title": c["subject"],
            "repo": name,
            "commit_time": c["commit_time"],
            "author": c["author"],
            "type": ctype,
            "confidence": round(conf, 2),
            "_match": reason,
            "files_changed": ", ".join(files),
            "diff_stat": f"+{ins}/-{dele}",
            "summary": (c["body"] or c["subject"]).strip()[:500],
        }
        if args.save_diffs and ctype == "Bug修复":
            os.makedirs(args.save_diffs, exist_ok=True)
            with open(os.path.join(args.save_diffs, c["short_hash"] + ".patch"),
                      "w", encoding="utf-8") as f:
                f.write(get_diff(repo_dir, c["commit_hash"]))
        records.append(rec)

    if args.type == "bugfix":
        records = [r for r in records if r["type"] == "Bug修复"]

    out = json.dumps(records, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"已抓取 {len(records)} 条提交 -> {args.out}")
    else:
        print(out)


if __name__ == "__main__":
    main()
