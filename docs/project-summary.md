# FlowRemote 项目工作总览（Week 5）

## 1. 项目是什么，现在到哪一步

FlowRemote 是一个"AI-RPA 流程的移动端监督与审批界面"：自动化在办公电脑上跑，人在手机上复核异常、批准写入、查看结果。第一个版本只做订单数据的校验与同步（TASK-1001 / Orders_September.xlsx / 100 条订单）。

当前状态：

- **已完成**：需求与状态机文档、两张交付图（数据模型、app 地图）、目录骨架、数据库与迁移、演示数据生成、领域模型、复核计数与审批闸门规则、38 个自动化测试。
- **未实现**：HTTP API、浏览器界面、真实的 AI 建议、OA/BI 连接器、登录与权限。

## 2. 交付物清单

| 路径 | 作用 | 状态 |
| --- | --- | --- |
| `docs/flowremote-prd.md` | 产品需求：11 屏拆解、9 条业务规则、数据模型、12 个待定问题 | 完成 |
| `docs/flowremote-state-machine-spec.md` | 状态机：L0-L4、转移表 T1-T19、14 条不变量、接口草案 | 完成 |
| `docs/flowremote-layered-architecture.html` | 七层架构图（浏览器可打开） | 完成 |
| `docs/week5/data-model.png` | 数据模型图：5 张表、6 条链接、字段类型与示例值 | 完成 |
| `docs/week5/app-map.png` | App 地图：7 个页面、12 个按钮、访问权限 | 完成 |
| `prompts/prompt-log.md` | Prompt 日志（课程要求，同时是 Handbook 第 17 节的 AI 披露） | 持续更新 |
| `pyproject.toml` | 项目定义；运行时依赖为空，可选依赖分组列出后续需要 | 完成 |
| `.env.example` / `.gitignore` / `.gitattributes` | 配置示例、忽略规则、行尾规范 | 完成 |
| `src/flowremote/contracts/` | 枚举、领域模型、时间格式 | 完成 |
| `src/flowremote/control_plane/db.py` | 数据库连接、迁移执行、方言隔离 | 完成 |
| `src/flowremote/control_plane/review.py` | 复核计数、审批闸门、审批构造 | 完成 |
| `src/flowremote/devtools/seed.py` | 演示数据生成与灌库 | 完成 |
| `src/flowremote/devtools/xlsx_writer.py` | 用标准库生成 .xlsx | 完成 |
| `tests/` | 38 个测试（单元 26 + 集成 12） | 全部通过 |
| `data/seed/`、`data/runtime/` | 生成物：源工作簿、注册表、数据库 | 被 git 忽略 |

## 3. 技术栈

| 类别 | 选择 | 说明 |
| --- | --- | --- |
| 语言 | Python 3.15（本机） | `pyproject.toml` 声明 `>=3.13`，用 `StrEnum` 等 3.11+ 特性 |
| 第三方依赖 | **无**（本阶段） | 整条链路在干净解释器上可跑，不需要联网安装 |
| 标准库 | `sqlite3`、`dataclasses`、`enum`、`unittest`、`zipfile` + XML、`csv`、`argparse`、`re`、`datetime` | 数据库、领域模型、测试、xlsx 生成分别对应 |
| 数据库 | SQLite（开发）→ PostgreSQL（目标） | 只用两种引擎共同支持的 SQL 子集；时间统一存 UTC ISO-8601 文本 |
| 版本控制 | Git 2.56.0 + GitHub 私有仓库 `Knight-hell` | `main` 分支，已推送 1 个提交 |
| 网络 | 本机 Clash Verge，混合端口 7897 | 只对 `github.com` 设代理；HTTP/1.1 + `http.postBuffer` 解决推送中途断流 |
| 原型工具 | Visily → Figma → Pixso | 报告里的设计演进记录 |
| 计划引入 | FastAPI + uvicorn + Pydantic（API 层）、浏览器界面（可选 PWA） | P2 起 |
| 测试框架 | `unittest` | 本机没有 pytest；命令为 `python -m unittest discover -s tests` |

## 4. 架构分层

| 层 | 目录 | 职责 | 状态 |
| --- | --- | --- | --- |
| 契约层 | `contracts/` | 枚举、领域模型、字段校验、时间格式 | 完成 |
| 控制面 | `control_plane/` | 数据库、迁移、复核计数、审批闸门 | 完成（动作接口待 P3） |
| AI 层 | `agent/` | 解释异常、给修正建议 | 空目录，P7 或 Note 2 |
| 执行层 | `rpa/` | 校验引擎、执行引擎 | 空目录，P5 |
| 连接器 | `connectors/` | OA / BI / 工作区适配 | 空目录，P5 |
| 接口层 | `api/` | HTTP 路由与事件流 | 空目录，P2 |
| 界面层 | `ui/` | 浏览器页面 | 空目录，P3-P5 |
| 开发辅助 | `devtools/` | 种子数据、模拟设备 | 种子数据完成 |

## 5. 数据模型

六张业务表（纸上画的是 5 张，多出的 `source_records` 用来存原始批次，这样"100 输入 / 88 通过"能用一条 SQL 查出来）：

| 表 | 主键 | 关键字段 | 关键约束 |
| --- | --- | --- | --- |
| `users` | `id` | name, email, role, device | `email UNIQUE`；`role IN ('operator','admin')` |
| `tasks` | `id` | workflow, batch_size, status, source_file, owner_id | `batch_size > 0`；状态受 CHECK 约束 |
| `source_records` | `(task_id, record_id)` | customer_name, customer_id, quantity, amount, outcome | `outcome IN ('passed','flagged')`；外键指向 tasks |
| `exceptions` | `id` | record_id, issue, flagged_fields, suggestion, confidence, status | `status IN ('unresolved','accepted','manual','skipped')`；`UNIQUE(task_id, record_id)` |
| `decisions` | `id` | exception_id, decision_id, action, new_value, by_user | `decision_id UNIQUE`（幂等键）；无 UPDATE 路径 |
| `approvals` | `id` | task_id, attempt, approver_id, approved_count, skipped_count | **`UNIQUE(task_id, attempt)`**：一次任务只能批准一次 |
| `schema_version` | `version` | applied_at | 记录已执行的迁移文件 |

关系：`users 1:N tasks`（Owner）、`tasks 1:N exceptions`、`exceptions 1:N decisions`、`users 1:N decisions`（By）、`tasks 1:N approvals`、`users 1:N approvals`（Approver）。

## 6. 接口说明

### 6.1 命令行接口

| 命令 | 作用 | 输出 |
| --- | --- | --- |
| `python src\flowremote\devtools\seed.py --reset` | 删库→建表→生成 xlsx/csv→灌数据 | 迁移名、文件路径、核对表 |
| `python src\flowremote\devtools\seed.py --verify-only` | 只读核对，不改数据 | 计数与三个案例 |
| `python src\flowremote\devtools\seed.py --db <URL>` | 指定数据库连接串 | 同上 |
| `python src\flowremote\control_plane\db.py` | 只应用迁移并列出表 | 引擎、URL、迁移、表清单 |
| `python -m unittest discover -s tests` | 跑全部测试 | 38 个测试，OK |

### 6.2 Python 接口

**`flowremote.control_plane.db.Database`**

| 成员 | 签名 | 语义 |
| --- | --- | --- |
| `__init__` | `(url: str \| None = None)` | 解析 `DATABASE_URL`：参数 → 环境变量 → 默认 SQLite 文件 |
| `connect` | `() -> Database` | 打开连接；SQLite 会设置 `foreign_keys=ON`、WAL、`busy_timeout` |
| `close` | `()` | 关闭连接 |
| `execute` | `(sql, params=())` | 执行一条语句，`?` 占位符在 PostgreSQL 上自动转 `%s` |
| `query` | `(sql, params=()) -> list[dict]` | 查询并返回字典列表 |
| `scalar` | `(sql, params=(), default=None)` | 取第一行第一列 |
| `transaction` | `()` 上下文管理器 | `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` |
| `apply_migrations` | `(directory=None) -> list[str]` | 按文件名顺序执行未应用的迁移，写 `schema_version` |
| `is_memory` | 属性 | 是否 `sqlite:///:memory:`（测试用） |

**`flowremote.contracts.models`**：`User`、`Task`、`SourceRecord`、`ExceptionItem`、`Decision`、`Approval`。每个模型都有 `from_row(row)`，并在构造时校验：枚举取值、`ORD-\d{3}` 的记录号、`confidence` 在 0–1、审批数量为正、`edit` 必须带值、`skip` 不能带值、未决异常不能带结论等。

**`flowremote.control_plane.review`**

| 函数 | 返回 | 语义 |
| --- | --- | --- |
| `tally(exceptions)` | `Tally` | 计数：accepted / manual / skipped / unresolved，以及 total / ready / reviewed |
| `proceed_enabled(exceptions)` | `bool` | 未决为 0 才为真（审批闸门） |
| `approved_records(exceptions)` | `list` | accepted + manual，即会写出的记录 |
| `skipped_records(exceptions)` | `list` | 被跳过的记录 |
| `build_approval(...)` | `Approval` | 生成审批行；未决 > 0、无可用记录、重复 attempt 分别抛 `ApprovalBlocked` / `DuplicateApproval` |

**`flowremote.contracts.enums`**：`TaskState`、`ExceptionStatus`、`DecisionAction`、`Role`、`Outcome`。数据库 CHECK、领域模型、未来 API 与界面共用这一套字符串。

### 6.3 SQL 接口

- 迁移文件：`src/flowremote/control_plane/migrations/0001_init.sql`，一条语句以分号加换行结束，语句内不出现分号。
- 已应用版本记录在 `schema_version`，重复执行安全。
- 索引：`exceptions(task_id, status)`、`source_records(task_id, outcome)`、`decisions(exception_id)`。

### 6.4 文件接口

- `data/seed/Orders_September.xlsx`：工作表 `Orders`，列依次为 `order_id, customer_name, customer_id, quantity, unit_price, amount, order_date`，共 100 行数据。
- `data/seed/customer_registry.csv`：列 `customer_id, customer_name, region, tier`，120 行。
- 连接串：`sqlite:///data/runtime/flowremote.db`（开发）或 `postgresql://user:pass@host:5432/db`（目标）。

### 6.5 计划中的 HTTP 接口（尚未实现，P2 起）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/tasks/{id}/validation` | 启动校验 |
| GET | `/tasks/{id}/validation` | 校验进度 |
| GET | `/tasks/{id}/exceptions?filter=` | 异常列表 |
| POST | `/tasks/{id}/exceptions/{recordId}/decisions` | 记录 Accept / Edit / Skip（带幂等键） |
| POST | `/tasks/{id}/approval` | 审批并派发执行 |
| GET | `/tasks/{id}/execution` | 执行进度 |
| GET | `/tasks/{id}/activity?cursor=` | 活动日志分页 |
| SSE | `/tasks/{id}/events` | 状态变更推送 |

## 7. 规则与不变量（三层保障）

| 规则 | 模型层 | 规则层 | 数据库层 |
| --- | --- | --- | --- |
| 未决为 0 才能审批 | — | `proceed_enabled` / `build_approval` | — |
| 一次任务只能批准一次 | `Approval` 校验 | `existing_attempts` | `UNIQUE(task_id, attempt)` |
| 决策只增不改 | `frozen=True` | 无更新函数 | 只有 INSERT 路径 |
| 决策幂等 | `decision_id` 非空 | — | `UNIQUE(decision_id)` |
| 状态取值受控 | 枚举强制转换 | — | `CHECK (... IN ...)` |
| 未决异常无结论 | `ExceptionItem` | — | — |
| 跳过不带值 | `ExceptionItem` | — | — |
| 通过的记录字段齐全 | `SourceRecord` | — | — |
| 审批数量为正 | `Approval` | `build_approval` | `CHECK (approved_count > 0)` |

## 8. 如何验证

```powershell
cd 'E:\knight hell'
python src\flowremote\devtools\seed.py --verify-only
python -m unittest discover -s tests
```

期望：seed 输出 `100 total (88 passed, 12 flagged)`、`12 unresolved`、`0 decisions`、`0 approvals`、`storyboard check ... OK`；测试输出 `Ran 38 tests ... OK`。

## 9. 已知限制

- 没有 HTTP 接口和界面，所以"能用的登录 + Feature 1"还没有完成（P2 起）。
- AI 建议是种子数据里的固定值（98% / 无建议 / 68%），没有真实模型调用。
- OA 和 BI 只是数据模型里的目标名称，没有连接器。
- 本机 Python 3.15 较新，Pydantic 等带编译扩展的库可能缺少预编译轮子，因此本阶段刻意零依赖。
- `data/seed/` 与 `data/runtime/` 被 git 忽略：克隆后需要跑一次 seed 才有演示数据（README 已写明）。

## 10. 与 Week 5 课程要求的对应

| 课程要求 | 对应产物 | 状态 |
| --- | --- | --- |
| 纸面数据模型（3-5 张表、字段类型、链接） | `docs/week5/data-model.png` | 完成（5 张表 + 1 张批次表） |
| App 地图（页面 / 按钮 / 字段 / 权限） | `docs/week5/app-map.png` | 完成（7 页 12 按钮） |
| Prompt 日志（AI 披露） | `prompts/prompt-log.md` | 进行中 |
| Working login | — | 待 P2 |
| Feature 1（复核 + 审批闸门） | 规则与模型已就绪 | 待 P3-P4 |
| Kanban 更新、weekly log | 你们手工维护 | 待办 |
| Demo Day 五问 | 答案模板已在对话中给出 | 可选落文档 |

## 11. 下一步

1. **P2 登录与隔离**：users 表 + 注册/登录/会话 + 按 owner 过滤 + admin 角色；验收是"第二个账号看不到第一个账号的任务"。
2. **P3 复核主线**：异常列表页 + Accept/Edit/Skip + decisions 只增 + 计数 12 → 0。
3. **P4 审批闸门**：审批页 + `UNIQUE(task_id, attempt)` 的实际写入。
4. **P5 执行与结果**：假 OA/BI 连接器 + 结果页 100/99/1/0。

提交命令（我这边的沙箱不能写 `.git`，需要你在终端执行）：

```powershell
cd 'E:\knight hell'
git add -A
git commit -m "P1: domain models, review rules and 38 tests"
git push
```
