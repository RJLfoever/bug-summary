# bug-summary — Git 提交抓取 → 飞书 Bug 知识库

一个符合 [Agent Skills 规范](https://agentskills.io/specification) 的 skill。
**输入一个仓库地址，每日自动抓取提交**，区分「需求开发」与「Bug修复」，
对 Bug修复 提交解读 **现象 / 原因 / 解决方案**，按统一格式写入飞书多维表格(Bitable)，
形成人和 agent 都能读、能检索的 Bug 知识库。

配合 [bug-solver](../bug-solver)（输入 Bug 现象 → 读取本表 → 推测原因与方案）形成闭环。

## 能力

- 本地仓库或 git URL 均可（URL 自动克隆/增量拉取）。
- 时间窗口默认最近 1 天，可用 `--days/--since/--until/--all` 调整。
- 提交分类：需求开发 / Bug修复 / 重构 / 文档 / 测试 / 其他（关键词 + Conventional Commits）。
- 增量幂等：按 `commit_hash` 去重，每日重复运行不产生重复记录。
- 两种运行模式：
  - **agent 模式**：agent 读 diff 深度解读现象/原因/方案（推荐，信息质量最高）
  - **auto 模式**：`auto_run.py` 一条命令无人值守（适合 cron / pi schedule / CI）

## 目录结构

```
bug-summary/
├── SKILL.md                 # 技能说明与操作步骤（agent 入口）
├── README.md
├── LICENSE
├── assets/
│   └── schema.json          # 飞书表格字段定义（唯一来源）
├── references/
│   └── schema.md            # 存储格式规范（人 & agent 可读）
└── scripts/
    ├── common.py            # 共用工具：lark-cli 封装、字段映射、去重
    ├── lark_init.py         # 创建飞书 Base+表，写入配置
    ├── git_collect.py       # 抓取提交 + 分类 + 输出 JSON（可存 diff）
    ├── lark_upsert.py       # 增量写入记录（按 commit_hash 去重）
    └── auto_run.py          # 自动模式：抓取→分类→写入 一条命令
```

## 快速开始

```bash
# 1) 初始化飞书表格（首次）
python scripts/lark_init.py --repo "<你的仓库>"

# 2) agent 深度解读模式（推荐）：抓取→读diff填字段→写入
python scripts/git_collect.py "<仓库>" --days 1 --save-diffs .tmp/diffs
#   （agent 读取 diff 后填写 references/schema.md 规定的记录 JSON）
python scripts/lark_upsert.py --records .tmp/bugfix_records.json --as-agent

# 3) 自动模式（每日定时）：一条命令
python scripts/auto_run.py "<仓库>" --days 1
```

## 依赖

- `git`
- `lark-cli`（已登录，具备 base 权限）
- `python` 3.8+

## License

[MIT](./LICENSE)
