# P3 实施报告：异常复核（Accept / Edit / Skip）

日期：2026-10-17
状态：完成，84 个测试全部通过（P2 的 66 + P3 新增 18）

## 1. 目标与验收

| 目标 | 验收方式 | 结果 |
| --- | --- | --- |
| 每条未决异常可 Accept / Edit / Skip | 页面出现三组控件；集成测试逐一点击 | 通过 |
| 每次动作写一条 decision（只增） | 查询 decisions 行数 | 通过 |
| 未决计数随之递减 | 页面与数据库同步变化 | 通过 |
| 未决为 0 时闸门打开 | 页面显示 "Every exception is resolved." | 通过 |
| 无建议时不能 Accept | 服务端返回 400，状态不变 | 通过 |
| 重复提交不重复计数 | 相同 decision_id 只落一行 | 通过 |
| 不能操作别人的任务 | 返回 404 | 通过 |

## 2. 执行步骤

1. 在 `control_plane/review.py` 里加纯函数 `decide()`：把"这条异常该变成什么状态"从 HTTP 与数据库里独立出来。
2. 新增 `api/routes/review.py`：一个 POST 端点，负责可见性、幂等、校验与事务写入。
3. 重构 `api/routes/tasks.py`：抽出 `load_task_page()` 供详情页与错误回显共用；异常查询左连接 `users` 取出复核人姓名；为每条未决行生成一次性 `decision_id`。
4. 重写 `ui/templates/task.html`：增加 Action 列（Accept / Skip / 值输入 + Save）与审批闸门横幅。
5. 补样式：迷你按钮、行内表单、闸门开/关两种状态。
6. 写 18 个测试：7 个规则单测 + 11 个端到端集成测试。
7. 工作区跑通后复制进项目，用真实演示库（12 条异常）做只读冒烟：页面出现 12 组 Accept/Skip/Edit，闸门显示 blocked。

## 3. 文件清单

### 新增

| 文件 | 作用 |
| --- | --- |
| `api/routes/review.py` | `POST /tasks/{id}/exceptions/{record}/decisions` |
| `tests/integration/test_decisions.py` | 11 个端到端测试 |

### 修改

| 文件 | 改动 |
| --- | --- |
| `control_plane/review.py` | 新增 `DecisionRejected`、`DecisionResult`、`decide()` |
| `api/routes/tasks.py` | 抽出 `load_task_page()` / `task_visible()`；异常查询带复核人；生成 `decision_id` |
| `api/app.py` | 注册决策路由 |
| `ui/templates/task.html` | Action 列 + 闸门横幅 |
| `ui/static/app.css` | 迷你按钮、行内表单、闸门样式 |
| `tests/unit/test_review.py` | 7 个 `decide()` 规则测试 |

## 4. 决策规则（`review.decide`）

| 动作 | 前置条件 | 结果状态 | 写入的值 |
| --- | --- | --- | --- |
| Accept | 该行有 AI 建议 | `accepted` | 建议值（例 C-1024） |
| Edit | 输入值非空 | `manual` | 操作员输入的值（例 6） |
| Skip | 无 | `skipped` | 不写值 |

拒绝的情况（抛 `DecisionRejected`，接口返回 400 并回显原因）：

- 行已经不是 `unresolved`（不能二次决策）
- Accept 但没有建议
- Edit 但值为空
- 未知动作

## 5. 接口契约

```
POST /tasks/{task_id}/exceptions/{record_id}/decisions
Content-Type: application/x-www-form-urlencoded

action=accept|edit|skip
value=<仅 edit 使用>
decision_id=<渲染时生成的一次性幂等键>
```

| 情况 | 响应 |
| --- | --- |
| 成功 | 303 → `/tasks/{task_id}` |
| 规则不满足 | 400，重渲染详情页并显示错误 |
| 重复的 `decision_id` | 303，不重复写入 |
| 未登录 | 303 → `/login` |
| 任务不可见 / 异常不存在 | 404 |

写入在一个事务里完成：先插 `decisions`，再更新 `exceptions` 的状态、结论值、复核人与时间。任何一步失败都会回滚。

## 6. 幂等与并发

- 每行在渲染时生成一个 `decision_id`（16 位十六进制），作为隐藏字段随表单提交。
- 双击或浏览器回退重发会带同一个键；服务端先查 `decisions.decision_id`，命中即当作已处理。
- 数据库另有 `UNIQUE(decision_id)` 兜底，即使两个请求同时到达，也只会落一行。

## 7. 页面变化

- 计数区的"未决"现在来自实时统计。
- 新增闸门横幅：未决 > 0 时显示 "N unresolved exception(s) still block approval." 与灰色的 Blocked；未决归零后变为绿色 "Every exception is resolved." 与 "Proceed (P4)"（按钮禁用，P4 才接审批页）。
- 异常表新增 Action 列：未决行是 Accept / Skip / 值输入 + Save；已决行显示结论值与复核人。
- 没有建议的行（ORD-081）Accept 按钮为禁用状态，并有 tooltip 说明原因。

## 8. 测试

| 文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `tests/unit/test_review.py` | 7（新增） | accept/edit/skip 结果、无建议拒绝、空值拒绝、未知动作、重复决策拒绝 |
| `tests/integration/test_decisions.py` | 11 | 三种动作落库、页面按钮、无建议 400、空值 400、重放不重复、跨账号 404、未登录跳转、闸门关闭/打开 |
| 其他（P1/P2 保留） | 66 | 模型、复核计数、审批闸门、数据库约束、认证、隔离 |
| **合计** | **84** | 全部通过 |

## 9. 真实数据冒烟

对 `data/runtime/flowremote.db`（种子生成的 TASK-1001，12 条异常）只读检查：

```
login status       : 303
task page status   : 200
accept buttons     : 12
skip buttons       : 12
edit inputs        : 12
blocked banner     : True
shows ORD-052      : True
shows 98%          : True
admin sees TASK-1001: True
```

## 10. 已知限制

- 没有 CSRF token；当前依赖 `SameSite=Lax` 会话 cookie 阻止跨站表单提交，正式部署前应加 token。
- 已决的行不能在页面上改判（模型支持追加新的 decision，但 P3 未开放入口；P4 的 Back to Review 会需要它）。
- 没有活动日志表：BR-10 要求的"每次状态变化留一条事件"在 P5 补。
- 闸门按钮只是展示，审批页与 `approvals` 写入在 P4。
- 大表性能未优化（每条异常一行表单，当前 12 行无压力）。

## 11. 下一步（P4）

- 审批页：汇总 100 / 1 skipped / 99 ready，展示源文件与两个目标。
- `POST /tasks/{id}/approval`：写 `approvals`（`UNIQUE(task_id, attempt)`），未决 > 0 时拒绝。
- Back to Review：允许改判并进行计数回滚。
- 把任务状态推进到 `pending_approval` → `executing`。
