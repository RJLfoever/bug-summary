# Bug 知识库存储格式（飞书多维表格）

本文档定义两个 skill 共用的飞书表格字段、写入记录结构、以及增量/幂等约定。
**人和 agent 都按此规范读写，保证可读性与一致性。**

## 表格定位

- 表格创建：`python scripts/lark_init.py`
- 定位信息（base_token / table_id / base_url / table_name）写入
  `~/.bugskills/config.json`（可用环境变量 `BUGSKILL_CONFIG` 覆盖），两个 skill 共用。

## 字段定义（assets/schema.json 为唯一来源）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 提交标题 | text（主字段） | Git 提交标题 |
| commit_hash | text | 完整 commit 哈希，**用于增量去重** |
| 仓库 | text | 仓库名 / URL |
| 提交时间 | datetime | 提交时间 |
| 作者 | text | 提交作者 |
| 类型 | select（单选） | 需求开发 / Bug修复 / 重构 / 文档 / 测试 / 其他 |
| 摘要 | text（多行） | 人可读的变更概述 |
| 现象 | text（多行） | Bug 现象：复现症状 / 报错 / 用户反馈 |
| 原因分析 | text（多行） | 根因分析：为什么会出问题 |
| 解决方案 | text（多行） | 如何修复 + 如何验证 |
| 涉及文件 | text | 变更文件（逗号分隔） |
| 变更统计 | text | diff 统计，如 +12/-3 |
| 关联链接 | text(url) | issue / PR / 工单链接 |
| 标签 | select（多选） | 空指针/内存泄漏/并发/性能/边界条件/配置/数据/依赖/兼容性/安全/逻辑错误/其他 |
| 置信度 | number | 分类/类型置信度 0-1 |
| 分析来源 | select（单选） | auto=脚本自动；agent=AI 深度分析 |
| 创建时间 | created_at | 记录写入时间 |

## 记录 JSON 结构（脚本输入/输出用英文键）

```json
{
  "commit_hash": "a1b2c3...",
  "title": "修复登录偶发空指针",
  "repo": "my-app",
  "commit_time": "2026-03-24T10:05:00+08:00",
  "author": "张三",
  "type": "Bug修复",
  "summary": "处理用户信息为空时的空指针",
  "phenomenon": "登录后偶发崩溃，日志 NPE at UserService.getProfile",
  "root_cause": "profile 可能为空，直接解引用未判空",
  "solution": "增加空值校验并返回默认值，补充单测",
  "files_changed": "src/UserService.java, src/User.java",
  "diff_stat": "+12/-3",
  "tags": ["空指针"],
  "confidence": 0.9,
  "analyzed_by": "agent",
  "link": "https://github.com/org/repo/issues/42"
}
```

## 分类规则（git_collect.py）

- 依据提交信息关键词 / Conventional Commits 前缀（`fix:` / `feat:` / `refactor:` ...）。
- 命中 bug 关键词（fix/bug/hotfix/修复/缺陷...）→ `Bug修复`；
  命中功能关键词（feat/add/新增/实现...）→ `需求开发`。
- 输出 `type` 与 `confidence`；低置信度（如同时含 fix 与 feat）时
  建议 agent 人工复核。

## 增量 / 幂等约定

- 去重键：`commit_hash`。写入前先读取表中已有 commit_hash 集合，已存在则跳过。
- 因此同一批提交重复运行（例如每日定时）不会产生重复记录。
- 默认窗口：最近 1 天；可用 `--days` / `--since` / `--until` / `--all` 调整。

## 可读性规范（给 agent 写字段时的要求）

- `摘要`：一句或几句自然语言说明“这次改动做了什么”，面向人阅读。
- `现象`：写清“能观察到的症状/报错/触发条件”，不要只写 commit 标题。
- `原因分析`：写“根因链条”（数据从哪来 → 哪个假设不成立 → 哪行代码出问题）。
- `解决方案`：写“怎么改 + 怎么验证（单测/回归/日志）”。
- 涉及文件、变更统计、标签尽量填全，便于检索与统计。
