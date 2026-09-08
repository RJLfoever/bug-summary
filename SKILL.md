---
name: bug-summary
description: "每日抓取 Git 仓库提交并分类（需求开发 vs Bug修复），对 Bug修复提交解读现象/原因/解决方案，按统一格式写入飞书多维表格(Bitable)形成可检索的 Bug 知识库。当用户需要『记录/总结提交』『抓取仓库每日提交』『把 bug 修复写进飞书表格』『维护 Bug 知识库』时使用。输入：仓库地址(本地路径或 git URL)，可选时间窗口。"
license: MIT
compatibility: "需要 git 与 lark-cli(已登录,具备 base 权限)。跨平台：支持 Python 3.8+。"
metadata:
  requires:
    bins: ["git", "lark-cli", "python"]
  version: "1.0.0"
---

# Bug Summary — Git 提交抓取与飞书 Bug 知识库

把仓库每日提交结构化后写入飞书多维表格，重点是**对 Bug修复 提交做「现象 / 原因 / 解决方案」解读**，
形成既方便人看、也方便 agent 检索的知识库。

## 流程总览

```text
1) 定位/初始化飞书表格  ── lark_init.py
2) 抓取提交并分类        ── git_collect.py
3) 解读 Bug修复 提交     ── agent 读 diff 填字段（本 skill 的核心价值）
4) 写入表格(增量去重)    ── lark_upsert.py
```

## 前置条件（首次使用）

```bash
lark-cli auth status          # 需已登录，具备 base 权限
python scripts/lark_init.py --repo "<默认仓库地址或路径>"   # 创建表格并写入配置
```

`lark_init.py` 会用 `assets/schema.json` 创建 Base+表，并把
`base_token/table_id/base_url` 写入 `~/.bugskills/config.json`（两个 skill 共用）。
创建后把表格地址发给用户确认。

## 使用步骤

### 第 1 步：抓取提交

```bash
python scripts/git_collect.py "<仓库>" --days 1 --out .tmp/commits.json
# 常用参数：--days N | --since ISO --until ISO | --all
# 若要读取 bug 的完整 diff 来分析，加 --save-diffs .tmp/diffs
```

输出每条提交的 `commit_hash / title / author / commit_time / type / confidence /
files_changed / diff_stat / summary`。`type` 已按关键词分类（需求开发 / Bug修复 / ...）。

### 第 2 步：复核分类（可选但推荐）

对 `confidence < 0.7` 或 `type=其他` 的提交，人工/agent 复核其分类：
- 提交信息含 fix/bug/修复/缺陷 → `Bug修复`
- 含 feat/add/新增/实现 → `需求开发`

### 第 3 步：深度解读 Bug修复 提交（核心）

对每条 `type=Bug修复` 的提交，**读取其 diff**（若用了 `--save-diffs`，直接读
`.tmp/diffs/<short>.patch`），然后按 `references/schema.md` 的「可读性规范」填写：

| 字段 | 要写什么 |
|------|---------|
| 摘要 | 这次改动做了什么（面向人） |
| 现象 | 能观察到的症状/报错/触发条件 |
| 原因分析 | 根因链条：数据来源→错误假设→出问题的代码 |
| 解决方案 | 怎么改 + 怎么验证（单测/回归/日志） |
| 标签 | 从 空指针/并发/性能/边界条件... 中选 |
| 关联链接 | 若有 issue/PR 号则填 |

同时把 `analyzed_by` 置为 `agent`、`confidence` 填分类置信度。

把所有 Bug修复 提交整理成 `references/schema.md` 中定义的记录数组，写入一个 JSON 文件
（例如 `.tmp/bugfix_records.json`）。

### 第 4 步：写入飞书表格

```bash
python scripts/lark_upsert.py --records .tmp/bugfix_records.json --as-agent
```

脚本按 `commit_hash` 增量去重，重复运行安全。写完后把表格地址与新增条数告知用户。

## 定时自动运行（无 LLM 的「每日自动抓取」）

需要无人值守、仅记录原始信息时，可用一条命令自动完成（不调用 LLM，字段打上 `analyzed_by=auto`）：

```bash
python scripts/auto_run.py "<仓库>" --days 1
```

接入定时任务示例：
- **pi schedule**：`schedule_prompt add --schedule "0 0 8 * * *" --prompt "运行 bug-summary skill 抓取 <仓库> 昨日提交"`
- **cron / 任务计划程序**：每天执行上面的 `auto_run.py`
- **GitHub Actions**：`on: schedule: - cron: '0 0 * * *'` 拉取本 skill 后运行

深度解读建议用 agent 路径（第 3 步）；定时路径保证每天都有原始记录兜底。

## 边界情况

- 仓库是 git URL → 自动克隆到 `~/.bugskills/cache/` 并增量 pull。
- 同一窗口重复运行 → 按 commit_hash 跳过，不重复。
- 没有任何 Bug修复 提交 → 提示无需写入，不创建空记录。
- 多语言提交信息 → 中英文关键词都覆盖。

## 权限

| 操作 | 所需 scope |
|------|-----------|
| 创建/读取表格 | `base:app:create` `base:app:read` `base:table:read` `base:field:read` |
| 写入记录 | `base:record:create` `base:record:read` |

> 提示：本 skill 与 `bug-solver` 共用同一张表格。`bug-solver` 输入「Bug 现象」读取该表
> 推测原因与解决方案，形成「记录 → 复用」闭环。
