#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化飞书 Bug 知识库：创建 Base + 首表（schema 来自 assets/schema.json），
并把 {base_token, table_id, base_url, table_name} 写入配置，供两个 skill 共用。
已初始化过则复用现有表格（幂等），不重复创建。

用法:
  python lark_init.py [--name "Bug知识库"] [--table "Bug记录"] [--schema assets/schema.json]
                      [--repo "<默认仓库>"] [--force]
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import run_lark, save_config, load_config  # noqa: E402


def get_first_table_id(base_token):
    data = run_lark(["+table-list", "--base-token", base_token, "--as", "user"])
    tables = []
    if isinstance(data, dict):
        inner = data.get("data", data)
        if isinstance(inner, dict):
            tables = inner.get("tables") or inner.get("items") or []
    if tables:
        t = tables[0]
        return t.get("table_id") or t.get("id") or t.get("table_token")
    return None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="Bug知识库")
    ap.add_argument("--table", default="Bug记录")
    ap.add_argument("--schema", default=os.path.join(here, "..", "assets", "schema.json"))
    ap.add_argument("--repo", help="可选：默认仓库名/URL，写入配置")
    ap.add_argument("--url", help="可选：默认仓库地址，写入配置")
    ap.add_argument("--force", action="store_true", help="即使已有配置也强制重新创建")
    args = ap.parse_args()

    cfg = load_config()

    # 幂等：已有 base 则复用
    if cfg.get("base_token") and not args.force:
        base_token = cfg["base_token"]
        table_id = cfg.get("table_id")
        if not table_id:
            table_id = get_first_table_id(base_token)
            cfg["table_id"] = table_id
            if args.repo:
                cfg["repo"] = args.repo
            save_config(cfg)
        print("✅ 已存在 Bug 知识库，直接复用：")
        print("  base_token :", base_token)
        print("  table_id   :", table_id)
        print("  表格地址    :", cfg.get("base_url", ""))
        return

    with open(args.schema, encoding="utf-8") as f:
        fields = json.load(f)
    fields_json = json.dumps(fields, ensure_ascii=False)

    print(f"正在创建飞书 Base: {args.name} / 表 {args.table} ...")
    data = run_lark([
        "+base-create", "--name", args.name, "--table-name", args.table,
        "--fields", fields_json, "--as", "user",
    ])

    inner = data.get("data", data) if isinstance(data, dict) else {}
    base = inner.get("base", {}) if isinstance(inner, dict) else {}
    table = inner.get("table", {}) if isinstance(inner, dict) else {}
    base_token = (base.get("base_token") or inner.get("base_token")
                  or inner.get("app_token") or inner.get("token"))
    table_id = table.get("id") or inner.get("table_id") or inner.get("table_token")
    base_url = base.get("url") or inner.get("url") or inner.get("base_url")
    if not base_token:
        raise SystemExit(f"未能从响应解析 base_token，请检查输出：\n{json.dumps(data, ensure_ascii=False)}")

    cfg.update({
        "base_token": str(base_token),
        "table_id": str(table_id) if table_id else None,
        "base_url": base_url or f"https://feishu.cn/base/{base_token}",
        "table_name": args.table,
        "base_name": args.name,
    })
    if args.repo:
        cfg["repo"] = args.repo
    if args.url:
        cfg["url"] = args.url
    save_config(cfg)

    print("\n✅ 初始化完成。配置已写入:", os.environ.get("BUGSKILL_CONFIG")
          or os.path.join(os.path.expanduser("~"), ".bugskills", "config.json"))
    print("  base_token :", cfg["base_token"])
    print("  table_id   :", cfg["table_id"])
    print("  表格地址    :", cfg["base_url"])


if __name__ == "__main__":
    main()
