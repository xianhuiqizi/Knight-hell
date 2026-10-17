# P4 实施报告：审批闸门与 approvals 写入

日期：2026-10-17
状态：完成，96 个测试全部通过（P3 的 84 + P4 新增 12）

## 1. 目标与验收

| 目标 | 验收方式 | 结果 |
| --- | --- | --- |
| 未决 > 0 时不能进入审批 | POST proceed 返回 400，状态不变 | 通过 |
| 未决 = 0 时可进入审批页 | 303 → `/tasks/{id}/approval`，状态 `pending_approval` | 通过 |
| 审批页显示 输入/跳过/可写/未决 | 页面数字与数据库一致 | 通过 |
| 审批写一行 approvals，且只写一次 | 重复提交仍只有 1 行 | 通过 |
| 审批后任务进入 executing | 查询 tasks.status | 通过 |
| Back to Review 可回到复核 | 状态回 `review_required`；审批后拒绝 | 通过 |
| 进入审批后不能再改判 | 决策接口返回 400 | 通过 |
| 不能审批别人的任务 | 404 | 通过 |

## 2. 执行步骤

1. 新增 `api/routes/approval.py`：四个端点（审批页、proceed、approve、back-to-review），每个都带守卫。
2. `load_task_page()` 增加"最新审批记录"查询（含审批人姓名），供任务页与审批页共用。
3. 复核路由加一道守卫：任务的 `status` 必须是 `review_required`，否则拒绝改判。
4. 任务页闸门改为四态：已审批 / 等待审批 / 可 proceed（表单按钮）/ 被阻塞。
5. 新增 `approval.html`：汇总、源文件、两个目标、提示语、Approve & Execute 与 Back to review。
6. 修掉一个计数 bug（见第 9 节）。
7. 12 个集成测试覆盖全部转移与守卫。
8. 用真实演示库跑完整链路：12 条决策 → 闸门 → 审批页 → 审批写入 → executing，然后重置数据。

## 3. 文件清单

### 新增

| 文件 | 作用 |
| --- | --- |
| `api/routes/approval.py` | 审批页 + 三个状态转移 |
| `ui/templates/approval.html` | 审批页 |
| `tests/integration/test_approval.py` | 12 个端到端测试 |

### 修改

| 文件 | 改动 |
| --- | --- |
| `api/routes/tasks.py` | 汇总 SQL 修正 ready；上下文加 approval |
| `api/routes/review.py` | 非 review_required 状态拒绝改判 |
| `api/app.py` | 注册审批路由 |
| `ui/templates/task.html` | 四态闸门 + 已审批横幅 |
| `ui/static/app.css` | 审批页面板、目标列表、提示条 |
| `tests/integration/test_decisions.py` | 旧的 "Proceed (P4)" 断言改为真正的 proceed 表单 |

## 4. 状态机

| From | 事件 | 守卫 | 结果 | 副作用 |
| --- | --- | --- | --- | --- |
| review_required | proceed | unresolved = 0 | pending_approval | 更新 updated_at |
| pending_approval | approve | 无已有审批、unresolved = 0、ready > 0 | executing | 写 approvals（attempt 1） |
| pending_approval | back-to-review | 无已有审批 | review_required | - |
| 其他 | 任意转移 | 状态不符 | 不变 | 303 或 400 |

## 5. 路由

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| GET | `/tasks/{id}/approval` | 审批页；非 pending/executing 时 303 回任务页；不可见 404 |
| POST | `/tasks/{id}/proceed` | 未决 > 0 → 400；否则 303 到审批页 |
| POST | `/tasks/{id}/approval` | 已审批 → 303（幂等）；状态不对/未决 > 0/没有可写记录 → 400；成功 → 303 |
| POST | `/tasks/{id}/back-to-review` | 已审批 → 400；否则回到 review_required |

## 6. 守卫与幂等

- 所有端点先做可见性判断（管理员可跨任务，操作员只能自己的），不可见统一 404。
- `approve` 若已存在审批行，直接重定向——双击不会写第二行；数据库的 `UNIQUE(task_id, attempt)` 仍是最后一道防线。
- proceed / approve / back 都会先校验当前状态，防止手工构造请求跳过步骤。
- 决策接口在任务离开 `review_required` 后拒绝写入。

## 7. 页面

- 任务页闸门四态：已审批（显示审批人/时间/条数）、等待审批（Open approval 链接）、可推进（Proceed 表单按钮）、被阻塞（Blocked）。
- 审批页：四个数字（输入/跳过/可写/未决）、源文件卡、两个目标（主写 99 条 / 次同步同一批，永不重复）、提示"验证不写库，只有审批才放行"、Approve & Execute 与 Back to review。
- 审批后审批页与任务页都显示审批记录，按钮消失。

## 8. 测试

| 文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `tests/integration/test_approval.py` | 12 | 未决阻塞、proceed、审批页守卫、审批写入与计数、重复审批、状态守卫、Back to Review（前后）、改判关闭、跨账号 404、未登录跳转 |
| 其他 | 84 | P1-P3 全部 |
| **合计** | **96** | 全部通过 |

## 9. 发现并修复的问题

**"可写条数"少算了通过的记录。** 原来 `ready` 只统计 `accepted + manual`（11 条），漏掉了本来就通过的 88 条，审批页会显示 "11 ready" 而不是故事板的 99。现已改为：

```sql
ready = (passed 的源记录数) + (accepted + manual 的异常数)
```

这样 `ready + skipped = input`（99 + 1 = 100），与报告和状态机文档一致。

## 10. 真实数据端到端结果

```
decisions posted  : 12
gate open         : True
proceed           : 303 /tasks/TASK-1001/approval
approval page     : 200
shows 99 ready    : True
shows 1 skipped   : True
approve button    : True
approve           : 303 /tasks/TASK-1001
approvals row     : [{'attempt': 1, 'approved_count': 99, 'skipped_count': 1, 'approver_id': 'USR-0001'}]
task status       : executing
decisions count   : 12
```

运行后已执行 `seed.py --reset` 恢复演示数据。

## 11. 已知限制

- 审批后任务停在 `executing`：执行引擎、进度与结果在 P5。
- 没有活动日志表（BR-10 的事件记录在 P5 补）。
- 审批没有"备注/拒绝原因"字段；需要的话可加 note 列。
- 没有 CSRF token，仍依赖 `SameSite=Lax`。
- 管理员也能审批任意任务（当前设计允许，若需限制可加角色判断）。

## 12. 下一步（P5）

- 执行层：两个目标各自的进度（99 written / 99 synced），最终结果页 99/100、42.8 s、99.0%。
- 活动日志：每个状态变化写一条事件并展示。
- 失败与重试：部分写入、同步失败的分支。
