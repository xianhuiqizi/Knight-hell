# P5 / Week 6 实施报告：执行进度、结果与活动日志（Feature 2）

日期：2026-10-25
状态：完成，186 个测试全部通过（W5 基线 147 + 本次新增 39）
起点：GitHub `main` 的 `54df659`（与本地一致，fetch 已核对）

## 1. 目标与验收

| 目标 | 验收方式 | 结果 |
| --- | --- | --- |
| 审批后自动生成执行记录 | 审批返回 303 后查 `execution_runs` | 通过：1 行，attempt 1，approved 99，written 0 |
| 分步推进且可观察 | 连续 POST step，看 JSON 计数 | 通过：20 → 40 → 60 → 80 → 99 |
| 执行完成推进任务状态 | 查 `tasks.status` | 通过：`executing` → `complete` |
| 结果页给出故事板数字 | GET `/tasks/{id}/results` | 通过：99/100、99.0%、跳过 1 条 |
| 活动日志逐条可查 | 页面 + `/activity.json` | 通过：15 条事件，页面与导出条数一致 |
| 部分失败可展示 | `FLOWREMOTE_EXECUTION_FAIL_AT=25` | 通过：停在第 24 条，run=partial，任务仍 executing |
| 重复点按不重复写 | 完成后再次 POST step / 再次审批 | 通过：计数不变，仍只有 1 个 run |
| 越权访问被拒 | 用户 B、匿名访问三类地址 | 通过：404 / 303 到登录页 |

## 2. 执行步骤

1. 核对 GitHub 与本地一致（`git fetch` + `ls-remote`：`54df659`），跑基线测试：147 passed / 18.21 s。
2. 用真实浏览器接口跑 W5 全链路（登录 → 上传 → 复核 → 审批），确认终点是 `executing` 且 `/execution`、`/results` 均 404。
3. 定 Feature 2 边界：进度 + 结果 + 活动日志，连接器为模拟实现，不接真实 OA/BI、不调用 AI。
4. 迁移 `0004_execution.sql`：`execution_runs`、`activity_events` 两张表与约束。
5. 契约层：`RunState`、`ActorKind` 两个枚举，`ExecutionRun`、`ActivityEvent` 两个模型（含不变量）。
6. 规则层：`rpa/execution.py` 的 `next_step()`（步长、完成、失败停止点）、`success_rate()`、`format_duration()`。
7. 连接器：`connectors/demo.py` 的 `SimulatedTarget`（不发任何网络请求）。
8. 活动日志：`control_plane/activity.py` 的 `log_event()` / `recent_events()`，事件与状态变化同事务。
9. 路由：`api/routes/execution.py` 五个端点（进度页、推进、状态 JSON、结果页、日志导出）。
10. 集成点：`approve()` 在既有事务里插入 run 与 `execution_approved` 事件。
11. 事件补齐：校验完成、每条决策、复核完成、退回复核、执行完成/失败。
12. 界面：`execution.html`、`results.html`、任务页入口、CSS 与轮询脚本（无 JS 时按钮仍可用）。
13. 测试：新增 19 个单元 + 20 个集成，修好 3 个旧测试文件的清理顺序。
14. 端到端验证：脚本 34 项检查全部通过（见第 10 节）。

## 3. 文件清单

### 新增

| 文件 | 作用 |
| --- | --- |
| `control_plane/migrations/0004_execution.sql` | 两张新表、索引、CHECK 与 UNIQUE |
| `control_plane/activity.py` | 追加式活动日志的写入与读取 |
| `rpa/__init__.py`、`rpa/execution.py` | 执行步进规则（纯函数，无数据库） |
| `connectors/__init__.py`、`connectors/demo.py` | 模拟目标端点 |
| `api/routes/execution.py` | 进度、推进、结果、日志导出 |
| `ui/templates/execution.html`、`ui/templates/results.html` | 两个新页面 |
| `tests/unit/test_execution_rules.py` | 19 个单元测试 |
| `tests/integration/test_execution.py` | 20 个集成测试 |
| `docs/p5-report.md` | 本报告 |

### 修改

| 文件 | 改动 |
| --- | --- |
| `contracts/enums.py` | 新增 `RunState`、`ActorKind` |
| `contracts/models.py` | 新增 `ExecutionRun`、`ActivityEvent` |
| `api/app.py` | 注册执行路由 |
| `api/routes/approval.py` | 审批建 run；proceed / back-to-review 记事件并包事务 |
| `api/routes/review.py` | 每条决策写一条事件（同事务） |
| `api/routes/tasks.py` | 任务页上下文带最新 run |
| `control_plane/order_validation.py` | 校验完成写一条 engine 事件 |
| `ui/templates/task.html` | 审批后给「View execution / View results」入口 |
| `ui/static/app.css`、`app.js` | 进度条、结果横幅、日志列表、轮询推进 |
| `tests/integration/test_approval.py`、`test_auth.py`、`test_decisions.py` | 清理表顺序补上两张新表（外键） |

## 4. 状态机

| From | 事件 | 守卫 | 结果 | 副作用 |
| --- | --- | --- | --- | --- |
| pending_approval | approve | 无已有审批、unresolved = 0、ready > 0 | executing | 写 approvals + `execution_runs`(attempt 1) + 事件 |
| executing | step | run.status = executing | executing | 计数 +20，事件仅在完成/失败时写 |
| executing | step（最后一步） | written + step ≥ approved | complete | `tasks.status=complete`、写 `finished_at`/`duration_ms`、`execution_completed` 事件 |
| executing | step（写入失败） | `FLOWREMOTE_EXECUTION_FAIL_AT` 命中 | 任务仍 executing；run=partial | `execution_failed` 事件；结果页显示已停在第几条 |
| executing / partial / complete | 任何 step | run 已结束 | 不变 | 无新行、无新事件 |
| review_required | proceed | unresolved = 0 | pending_approval | `review_completed` 事件 |
| pending_approval | back-to-review | 无已有审批 | review_required | `review_reopened` 事件 |

T14–T18 中，T14（进度）、T15（完成）、T16（失败记录，任务态保持 executing）、T18（回到首页）已落地；T17（retry）未实现，见第 11 节。

## 5. 路由

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/tasks/{id}/execution` | 进度页；无 run 或未审批 → 303 回任务页；已结束 → 303 到结果页 |
| POST | `/tasks/{id}/execution/step` | 推进 20 条；`Accept: application/json` 返回快照，否则 303 |
| GET | `/tasks/{id}/execution.json` | 轮询快照：status / approved / written / synced / progress_pct |
| GET | `/tasks/{id}/results` | 结果页；仍在执行 → 303 回进度页 |
| GET | `/tasks/{id}/activity.json` | 审计日志导出（含 payload） |

所有端点先做可见性判断：operator 只能看自己的任务，admin 可看全部，不可见统一 404。

## 6. 不变量

| 不变量 | 模型层 | 数据库层 |
| --- | --- | --- |
| 一次审批只启动一个 run | — | `UNIQUE (task_id, attempt)` + 审批幂等守卫 |
| 写入不超过批准数 | `ExecutionRun` 构造校验 | `CHECK (written_count <= approved_count)` |
| 次级目标不超前于主写 | `ExecutionRun` 构造校验 | `CHECK (synced_count <= written_count)` |
| 结束的 run 必须有结束时间 | `ExecutionRun` 构造校验 | — |
| 计数只增 | 无 UPDATE 路径以外的方法（路由只加不减） | — |
| 每个状态变化一条事件 | `ActivityEvent` 校验非空字段 | — |

## 7. 页面

- **进度页**：approved / written / synced / skipped 四个数字、进度条、两个目标（标注 simulated）、自动推进；无 JavaScript 时用「Run next 20 records」按钮。
- **结果页**：完成或中断横幅、success（99/100）、duration、success rate（99.0%）、活动日志（时间 + 人/引擎徽标 + 一句话 + 操作者）、返回首页与 JSON 导出。
- **任务页**：审批后不再只有徽标，而是「View execution」或「View results」；part run 时横幅写「Execution stopped early」。

## 8. 测试

| 文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `tests/unit/test_execution_rules.py` | 19 | 步长、边界、失败停止点、非法输入、成功率、时长格式、两个模型的校验 |
| `tests/integration/test_execution.py` | 20 | 审批建 run、幂等、页面守卫、五步完成、完成后无操作、部分失败、结果数字、日志与导出、越权、匿名、管理员、轮询端点、无 JS 按钮 |
| 既有测试 | 147 | 全部通过（仅清理顺序修正） |
| **合计** | **186** | 23.5 s |

## 9. 发现并修复的问题

1. **新表外键导致三个旧测试无法清理数据库。** `test_approval` / `test_auth` / `test_decisions` 的 `DELETE FROM tasks` 撞上 `execution_runs` 与 `activity_events` 的外键。修正：清理顺序补上两张新表（先子后父）。
2. **任务页审批后是死路。** 原来只显示「Approved」徽标，用户不知道下一步。现在按 run 状态给入口。
3. **"0 ms" 的时长。** 时间戳按项目约定精确到秒，同一秒内跑完会显示 0 ms。修正：`format_duration(0)` 显示 `< 1 s`，不编造数字。
4. **事件与状态分开写会撒谎。** proceed / approve / back-to-review / 决策都改成在同一事务里写事件。
5. **时长把等待时间算进去了。** 原先 `started_at` 在建 run（审批）时写下，操作员隔几分钟再打开执行页，`duration` 就把这段等待算成执行时间（实测出现过 44.0 s）。修正：第一步真正开始时才设定 `started_at`，结果页的 duration 现在约 1–3 s。
6. **审批页留了一句过期文案。** 完成审批后页面仍写「Execution itself … arrives in P5」。修正：已审批时改为指向结果页的链接，未审批时说明「执行只在此审批后开始，且目标是模拟的」。

## 10. 真实数据端到端结果

`python tmp/w6-probe/probe_feature2.py`（新起服务、`seed.py --reset`、走完整旅程）：

```
resolved              : 8 accepted / 3 manual / 1 skipped
approve               : 303, run RUN-TASK-1001-1, approved 99, written 0
steps                 : 20 40 60 80 99  (5 steps)
run                   : complete, written 99, synced 99
task                  : complete
results               : 99/100, 99.0%, duration measured, 15 log lines
activity events       : 12 exception_decided + review_completed + execution_approved + execution_completed
other account         : 404 on /execution, /results, /execution/step
summary               : 34/34 checks passed
```

另有一份只读探针 `tmp/w6-probe/probe_flow.py` 覆盖 W5 行为（登录、越权、错误输入、上传校验、审批闸门）：59/60 通过；唯一失败项是第 11 条已知偏差。

## 11. 已知限制

- **失败状态落在 run 上，不在 task 上。** `tasks.status` 的 CHECK 只有 6 个值，重建该表才能加 `partial`；当前用 `execution_runs.status` + 事件表达，UI 明确写「stopped early」。
- **没有 retry（T17）。** 部分失败后只能重新走审批；重试语义留到下一周。
- **连接器是模拟的。** 没有网络请求，结果页与进度页都标 `simulated`；周报与证据里不得写成已写入真实 OA/BI。
- **时长精度到秒。** 同一秒内完成显示 `< 1 s`；真实演示（浏览器 400 ms 一轮）通常 2 s 左右。
- **0 异常任务仍停在 `review_required`（PRD FR-4.5 未满足）。** 实测见第 10 节探针：干净文件 0 异常，状态仍 `review_required`，但闸门已开、可以 proceed，不是死路；本周只记录，未改。
- **没有 CSRF token。** 沿用 `SameSite=Lax`，与 W5 相同。
- 管理员可以推进别人的 run（与审批一致，当前设计允许）。

## 12. 下一步

1. 失败重试（T17）：只重跑未完成的记录，新增 `execution_runs.attempt` 递增。
2. 0 异常任务直达 `pending_approval`（FR-4.5）。
3. AI 功能（异常解释与建议）——后续周的独立功能位。
4. 纸面 App Map / 数据模型补上两张新表与两个新页面，作为 W6 证据。
5. 外部用户测试（W7）：请一位同学在无指导下走完「上传 → 复核 → 审批 → 执行 → 结果」。
