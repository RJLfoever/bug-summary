#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bug-summary / bug-solver 共用工具：通过 lark-cli 读写飞书多维表格(Bitable)。

前置条件：
  - 已安装 lark-cli 并登录（lark-cli auth login）
  - 具备 base 相关权限（base:app:create / base:record:create / base:record:read ...）
配置：默认读取 ~/.bugskills/config.json（可用环境变量 BUGSKILL_CONFIG 覆盖），
由 lark_init.py 写入 {base_token, table_id, base_url, table_name, repo, url}。
"""
import json, os, subprocess, sys, datetime, shutil, glob, tempfile

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CONFIG_PATH = os.environ.get("BUGSKILL_CONFIG") or os.path.join(
    os.path.expanduser("~"), ".bugskills", "config.json"
)


def _lark_base_cmd():
    """返回调用 lark-cli 的基础命令列表（兼容 Windows npm .cmd 包装）。"""
    exe = shutil.which("lark-cli")
    if exe and not exe.lower().endswith(".cmd"):
        return [exe]
    # Windows：lark-cli 是 .cmd，实际是 node 脚本，直接用 node 运行
    runjs = os.environ.get("LARK_CLI_RUNJS")
    if not runjs:
        patterns = [
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm",
                         "node_modules", "@larksuite", "cli", "scripts", "run.js"),
            os.path.join(os.environ.get("APPDATA", ""), "npm",
                         "node_modules", "@larksuite", "cli", "scripts", "run.js"),
        ]
        for p in patterns:
            if os.path.exists(p):
                runjs = p
                break
    if runjs and os.path.exists(runjs):
        node = shutil.which("node") or "node"
        return [node, runjs]
    if exe:
        return [exe]  # 兜底
    raise RuntimeError(
        "找不到 lark-cli。请安装并确保其在 PATH（或设置 LARK_CLI_RUNJS 指向 run.js）。"
    )

# 记录英文键 -> 飞书表格字段中文名
FIELD_MAP = {
    "commit_hash": "commit_hash",
    "title": "提交标题",
    "repo": "仓库",
    "commit_time": "提交时间",
    "author": "作者",
    "type": "类型",
    "summary": "摘要",
    "phenomenon": "现象",
    "root_cause": "原因分析",
    "solution": "解决方案",
    "files_changed": "涉及文件",
    "diff_stat": "变更统计",
    "tags": "标签",
    "confidence": "置信度",
    "analyzed_by": "分析来源",
    "link": "关联链接",
}

# 按英文键区分的字段类型
TEXT_FIELDS = {
    "commit_hash", "repo", "author", "summary", "phenomenon",
    "root_cause", "solution", "files_changed", "diff_stat", "link", "title",
}
SINGLE_SELECT = {"type", "analyzed_by"}
MULTI_SELECT = {"tags"}
NUMBER_FIELDS = {"confidence"}
DATETIME_FIELDS = {"commit_time"}

# 类型/分析来源/标签 允许的选项（需与 assets/schema.json 一致）
TYPE_OPTIONS = ["需求开发", "Bug修复", "重构", "文档", "测试", "其他"]
SOURCE_OPTIONS = ["auto", "agent"]
TAG_OPTIONS = [
    "空指针", "内存泄漏", "并发", "性能", "边界条件", "配置",
    "数据", "依赖", "兼容性", "安全", "逻辑错误", "其他",
]


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def run_lark(args, expect_json=True):
    """执行 lark-cli base <args>，返回解析后的 JSON 或原始文本。"""
    cmd = _lark_base_cmd() + ["base"] + [str(a) for a in args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    out = proc.stdout.strip()
    err = proc.stderr.strip()
    if proc.returncode != 0:
        raise RuntimeError(
            f"lark-cli 执行失败: {' '.join(cmd)}\nSTDERR: {err}\nSTDOUT: {out}"
        )
    if not expect_json:
        return out
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return out


def extract_records(payload):
    """从 lark-cli 各种返回结构里尽力提取记录列表。"""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("items", "records", "data", "rows", "results", "record_list"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
        # 嵌套 data.items 等
        for k in ("data", "result"):
            if isinstance(payload.get(k), dict):
                v = payload[k].get("items") or payload[k].get("records")
                if isinstance(v, list):
                    return v
    return []


def get_field(rec, name):
    """从单条记录取字段值（兼容 {fields:{...}} 与扁平结构）。"""
    if not isinstance(rec, dict):
        return None
    if name in rec:
        return rec[name]
    f = rec.get("fields")
    if isinstance(f, dict) and name in f:
        return f[name]
    return None


def to_dt_str(value):
    """把 ISO 时间转为 'YYYY-MM-DD HH:MM'（飞书 datetime CellValue）。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s[:16]


def to_record_payload(rec):
    """把英文键记录映射为飞书 CellValue 字段映射。"""
    payload = {}
    for eng, cn in FIELD_MAP.items():
        if eng not in rec:
            continue
        v = rec[eng]
        if v is None or v == "" or v == []:
            continue
        if eng in TEXT_FIELDS:
            payload[cn] = str(v)
        elif eng in SINGLE_SELECT:
            payload[cn] = [str(v)]
        elif eng in MULTI_SELECT:
            vals = v if isinstance(v, list) else [v]
            payload[cn] = [str(x) for x in vals]
        elif eng in NUMBER_FIELDS:
            try:
                payload[cn] = float(v)
            except Exception:
                payload[cn] = 0
        elif eng in DATETIME_FIELDS:
            dt = to_dt_str(v)
            if dt:
                payload[cn] = dt
    return payload


def get_existing_hashes(base_token, table_id):
    """返回表中已存在的 commit_hash 集合（用于增量去重）。"""
    hashes = set()
    for rec in list_records(base_token, table_id, field_ids=["commit_hash"]):
        v = rec.get("commit_hash")
        if v:
            if isinstance(v, list):
                v = v[0] if v else None
            if v:
                hashes.add(str(v).strip())
    return hashes


def _ndjson_path():
    d = os.path.join(tempfile.gettempdir(), "bugskills")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "records.ndjson")


def fetch_records(cmd_args_base, limit):
    """以 ndjson 形式读取记录并解析成 字段名->值 的字典列表（含 record_id）。"""
    path = _ndjson_path()
    cmd = cmd_args_base + ["--limit", str(limit), "--format", "ndjson",
                           "--output", path, "--overwrite", "--as", "user"]
    run_lark(cmd, expect_json=False)
    recs = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except Exception:
                        pass
    return recs


def list_records(base_token, table_id, field_ids=None, filter_json=None, limit=2000):
    """列出表中记录（可选字段投影与过滤）。"""
    cmd = ["+record-list", "--base-token", base_token, "--table-id", table_id]
    for fid in (field_ids or []):
        cmd += ["--field-id", fid]
    if filter_json:
        cmd += ["--filter-json", json.dumps(filter_json, ensure_ascii=False)]
    return fetch_records(cmd, limit)


def search_records(base_token, table_id, keyword, search_fields, field_ids=None,
                   filter_json=None, limit=2000):
    """全文检索记录。"""
    cmd = ["+record-search", "--base-token", base_token, "--table-id", table_id,
           "--keyword", keyword]
    for f in search_fields:
        cmd += ["--search-field", f]
    for fid in (field_ids or []):
        cmd += ["--field-id", fid]
    if filter_json:
        cmd += ["--filter-json", json.dumps(filter_json, ensure_ascii=False)]
    return fetch_records(cmd, limit)


def count_created(data):
    """尽力统计批量创建成功的记录数。"""
    if isinstance(data, dict):
        for k in ("total", "created", "count", "success_count"):
            if isinstance(data.get(k), (int, float)):
                return int(data[k])
    return None


def batch_create(base_token, table_id, records):
    """分批创建记录（每批 <=200），返回创建条数。"""
    created = 0
    for i in range(0, len(records), 200):
        chunk = records[i:i + 200]
        payload = {"create_records": chunk}
        data = run_lark([
            "+record-batch-create", "--base-token", base_token, "--table-id", table_id,
            "--json", json.dumps(payload, ensure_ascii=False), "--as", "user",
        ])
        n = count_created(data)
        created += n if n is not None else len(chunk)
    return created
