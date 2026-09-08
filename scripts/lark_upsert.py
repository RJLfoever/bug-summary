#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把记录写入飞书 Bug 表格（增量、幂等）。

用法:
  python lark_upsert.py --records records.json [--base-token X] [--table-id Y]
  python lark_upsert.py --records records.json --dry-run   # 仅预览不写入

records.json 结构（英文键数组，见 references/schema.md）：
  [{"commit_hash": "...", "title": "...", "repo": "...", "commit_time": "ISO",
    "author": "...", "type": "Bug修复", "summary": "...", "phenomenon": "...",
    "root_cause": "...", "solution": "...", "files_changed": "...", "diff_stat": "+1/-1",
    "tags": ["空指针"], "confidence": 0.9, "analyzed_by": "agent", "link": "..."}]

行为：
  - 按 commit_hash 去重：表中已存在的提交会跳过（保证每日重跑幂等）。
  - type 必须是 需求开发/Bug修复/重构/文档/测试/其他 之一。
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    load_config, to_record_payload, get_existing_hashes, batch_create,
    TYPE_OPTIONS,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True, help="记录 JSON 文件路径")
    ap.add_argument("--base-token")
    ap.add_argument("--table-id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--as-agent", action="store_true",
                    help="把记录标记为 agent 深度分析（analyzed_by=agent）")
    args = ap.parse_args()

    with open(args.records, encoding="utf-8") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise SystemExit("--records 应为 JSON 数组")

    cfg = load_config()
    base_token = args.base_token or cfg.get("base_token")
    table_id = args.table_id or cfg.get("table_id")
    if not base_token or not table_id:
        raise SystemExit("未找到 base_token/table_id。请先运行 lark_init.py 初始化。")

    if args.as_agent:
        for r in records:
            r["analyzed_by"] = "agent"

    # 校验/规范化
    for r in records:
        if r.get("type") and r["type"] not in TYPE_OPTIONS:
            r["type"] = "其他"
        if not r.get("analyzed_by"):
            r["analyzed_by"] = "auto"
        if not r.get("title"):
            r["title"] = (r.get("summary") or r.get("commit_hash") or "")[:200]

    existing = get_existing_hashes(base_token, table_id)
    new_records, skipped = [], 0
    for r in records:
        h = (r.get("commit_hash") or "").strip()
        if h and h in existing:
            skipped += 1
            continue
        existing.add(h)
        new_records.append(r)

    if args.dry_run:
        print(f"[dry-run] 将新增 {len(new_records)} 条，跳过 {skipped} 条（已存在）。")
        for r in new_records[:10]:
            print(" -", r.get("title", ""), "|", r.get("type", ""), "|", r.get("commit_hash", ""))
        return

    if not new_records:
        print(f"无新增记录（{skipped} 条已存在）。")
        return

    payloads = [to_record_payload(r) for r in new_records]
    created = batch_create(base_token, table_id, payloads)
    print(f"✅ 写入完成：新增 {created} 条，跳过 {skipped} 条已存在。")
    print("表格地址:", cfg.get("base_url", ""))


if __name__ == "__main__":
    main()
