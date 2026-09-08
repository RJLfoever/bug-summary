#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动模式：一条命令完成「抓取提交 -> 分类 -> 写入飞书 Bug 表格」。

适合定时任务（cron / pi schedule / GitHub Actions schedule）每日自动运行：
  python auto_run.py <repo> [--days 1]

说明：
  - 首次运行会自动创建飞书 Base（需 lark-cli 已登录）。
  - 按 commit_hash 增量去重，重复运行安全。
  - 该模式不调用 LLM：现象/原因/解决方案仅填入提交信息中的原始描述，
    并标注 analyzed_by=auto，提示可用 agent 深度分析补充。
  - 若要深度解读，可先运行本脚本，再用 bug-solver 读取表格辅助分析。
"""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run_py(name, *args):
    p = subprocess.run(
        [sys.executable, os.path.join(HERE, name)] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(p.stdout)
    if p.returncode != 0:
        raise RuntimeError(p.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", help="仓库本地路径或 git 地址（缺省用配置中的 repo）")
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()

    from common import load_config  # noqa: E402
    cfg = load_config()

    if not cfg.get("base_token"):
        print("未初始化，正在创建飞书 Bug 知识库...")
        run_py("lark_init.py")
        cfg = load_config()

    repo = args.repo or cfg.get("repo")
    if not repo:
        raise SystemExit("未提供仓库地址，且配置中没有默认 repo。请传 <repo> 或先 lark_init --repo")

    tmp = os.path.join(os.path.dirname(__file__), "..", ".tmp")
    os.makedirs(tmp, exist_ok=True)
    collect_json = os.path.join(tmp, "commits.json")

    print(f"抓取仓库 {repo} 最近 {args.days} 天的提交...")
    run_py("git_collect.py", repo, "--days", str(args.days), "--out", collect_json)

    with open(collect_json, encoding="utf-8") as f:
        records = json.load(f)

    # 仅保留 Bug修复 提交，并填充启发式字段
    kept = []
    for r in records:
        if r["type"] != "Bug修复":
            continue
        r["analyzed_by"] = "auto"
        r.setdefault("summary", r.get("title", ""))
        r.setdefault("phenomenon",
                     r.get("summary", "") or "(自动模式：请用 agent 结合 diff 补充现象)")
        r.setdefault("root_cause", "(自动模式：请用 agent 分析提交 diff 补充根因)")
        r.setdefault("solution",
                     f"见提交 {r.get('commit_hash','')[:8]}，改动文件：{r.get('files_changed','')}")
        kept.append(r)

    if not kept:
        print("最近窗口内没有 Bug修复 提交，无需写入。")
        return

    bugfix_json = os.path.join(tmp, "bugfix_records.json")
    with open(bugfix_json, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)
    run_py("lark_upsert.py", "--records", bugfix_json)


if __name__ == "__main__":
    main()
