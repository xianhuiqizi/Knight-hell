# P2 实施报告：登录、会话与数据隔离

日期：2026-10-17
范围：P2（课程 Week 5 的 "working login" 部分）
状态：完成，66 个测试全部通过

## 1. 目标与验收

| 目标 | 验收方式 | 结果 |
| --- | --- | --- |
| 能注册、登录、登出 | 集成测试 + 页面渲染 | 通过 |
| 未登录访问被挡回登录页 | GET / 与 /tasks/{id} 返回 303 → /login | 通过 |
| 第二个账号看不到第一个账号的任务 | 两个 operator 各自只看到自己的任务 | 通过 |
| admin 能看到全部任务 | 管理员首页包含两个任务 | 通过 |
| 伪造的会话 cookie 无效 | 篡改 payload 后视为未登录 | 通过 |
| 密码不以明文存储 | PBKDF2-HMAC-SHA256 + 每用户随机盐 | 通过 |

## 2. 执行步骤

1. 复制现有 `src/` 与 `tests/` 到工作区，建立隔离的 P2 开发副本。
2. 先写认证原语：密码哈希（`control_plane/auth.py`）、签名会话（`api/sessions.py`）、表单解析（`api/forms.py`）。
3. 写应用工厂与依赖：`api/app.py`、`api/deps.py`、`api/rendering.py`。
4. 写路由：`api/routes/session.py`（注册/登录/登出）、`api/routes/tasks.py`（任务列表/详情）。
5. 写五个 Jinja 模板与一份深色样式表。
6. 写测试：6 个密码测试、5 个会话测试、17 个认证与隔离集成测试。
7. 在工作区跑通后复制进 `E:\knight hell`，重建演示数据，再跑一遍。
8. 冒烟验证：用 ASGI `TestClient` 覆盖页面、静态资源与重定向（沙箱不允许启动/停止真实服务进程）。

## 3. 文件清单

### 新增

| 文件 | 作用 |
| --- | --- |
| `control_plane/auth.py` | 密码哈希与校验、创建用户、按邮箱认证 |
| `api/__init__.py` | 包标记 |
| `api/sessions.py` | HMAC-SHA256 签名的会话 cookie；开发密钥持久化 |
| `api/forms.py` | 解析 `application/x-www-form-urlencoded`（不依赖 python-multipart） |
| `api/rendering.py` | 统一的 Jinja 渲染入口 |
| `api/deps.py` | 每请求一个数据库连接；从 cookie 解析当前用户 |
| `api/app.py` | 应用工厂：迁移、模板、静态文件、路由注册 |
| `api/routes/session.py` | `/login`、`/signup`、`/logout` |
| `api/routes/tasks.py` | `/`（任务列表）与 `/tasks/{id}`（详情），含角色过滤 |
| `ui/templates/base.html` | 顶栏、用户标识、退出按钮 |
| `ui/templates/login.html` | 登录页 |
| `ui/templates/signup.html` | 注册页 |
| `ui/templates/home.html` | 任务卡片列表 |
| `ui/templates/task.html` | 任务详情：输入/通过/标记/未决/可写 + 异常表 |
| `ui/static/app.css` | 深色移动端样式（响应式到 640px） |
| `tests/unit/test_passwords.py` | 6 个密码测试 |
| `tests/unit/test_sessions.py` | 5 个会话测试 |
| `tests/integration/test_auth.py` | 17 个认证/隔离/页面测试 |

### 修改

| 文件 | 改动 |
| --- | --- |
| `control_plane/db.py` | SQLite 连接加 `check_same_thread=False`（FastAPI 线程池需要） |
| `devtools/seed.py` | 用户带密码哈希；新增 admin 账号；打印演示凭据 |

## 4. 认证设计

### 4.1 密码

- 算法：PBKDF2-HMAC-SHA256，200,000 次迭代，每用户 16 字节随机盐。
- 存储格式：`pbkdf2_sha256$200000$<salt-b64>$<hash-b64>`（存在 `users.password_hash`）。
- 校验用 `hmac.compare_digest`，避免时序泄露。
- 最短 8 位；未知邮箱与错误密码返回同样的失败页面。

### 4.2 会话

- Cookie 名：`flowremote_session`；属性：`HttpOnly`、`SameSite=Lax`、`Path=/`，有效期 8 小时。
- 内容：`base64url({"uid","exp"}) + "." + HMAC-SHA256(secret, payload)`。
- 校验：先验签（常量时间比较），再检查过期时间。
- 密钥来源：`SESSION_SECRET` 环境变量；没有时首次启动生成 `data/runtime/session.key` 并复用（重启不掉登录，文件已被 git 忽略）。

### 4.3 为什么不装 itsdangerous / python-multipart

这两个包分别用于 Starlette 的 `SessionMiddleware` 和 FastAPI 的 `Form(...)`。安装它们需要联网，而执行环境只放行 git 流量。改用标准库后：P2 零新增依赖，部署更简单，且签名与解析逻辑都只有几十行、可被测试覆盖。

## 5. 路由与行为

| 方法 | 路径 | 未登录 | 已登录 | 说明 |
| --- | --- | --- | --- | --- |
| GET | `/login` | 200 登录页 | 303 → `/` | 支持 `?next=`，只接受站内相对路径 |
| POST | `/login` | 401 + 错误提示 | 303 → `next` 或 `/` | 成功后写 cookie |
| GET | `/signup` | 200 注册页 | 303 → `/` | |
| POST | `/signup` | 400（邮箱重复/密码不一致/太短）或 303 | 303 → `/` | 成功后自动登录 |
| POST | `/logout` | 303 → `/login` | 303 → `/login`，清除 cookie | |
| GET | `/` | 303 → `/login` | 200 任务列表 | operator 只看自己，admin 看全部 |
| GET | `/tasks/{id}` | 303 → `/login` | 200 详情；无权访问返回 404 | 404 而非 403，避免泄露任务是否存在 |

## 6. 数据隔离

```sql
-- operator
SELECT ... FROM tasks t WHERE t.owner_id = ? ORDER BY t.updated_at DESC
-- admin
SELECT ... FROM tasks t ORDER BY t.updated_at DESC
```

任务详情页复用同一条件，因此"别人任务的 URL"对 operator 直接 404。所有查询参数都用占位符绑定，没有字符串拼接的用户输入。

## 7. 页面

| 页面 | 内容 |
| --- | --- |
| 登录 | 产品标题、"Work email / Password"、错误提示、注册入口 |
| 注册 | 姓名、邮箱、密码、确认密码、登录入口 |
| 首页 | 任务卡片：任务号、状态徽章、工作流名、源文件与批次、通过/异常/未决三个数字 |
| 任务详情 | 五个计数（输入/通过/标记/未决/可写）与异常表（记录号、问题、字段、原值、建议、匹配度、状态） |

样式为深色主题（`#080d17` 背景、`#3b82f6` 主色），手机宽度下表格可横向滚动。

## 8. 测试

| 文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `tests/unit/test_passwords.py` | 6 | 正确/错误密码、盐随机、短密码拒绝、损坏哈希、存储格式 |
| `tests/unit/test_sessions.py` | 5 | 正常、篡改 payload、换密钥、过期、垃圾输入 |
| `tests/integration/test_auth.py` | 17 | 未登录跳转、错误密码、登录成功、两个账号隔离、admin 全见、404、退出、伪造 cookie、注册成功/重复邮箱/密码不一致/短密码、任务详情计数、静态样式 |
| 其他（P1 保留） | 38 | 模型规则、复核计数、审批闸门、数据库约束 |
| **合计** | **66** | 全部通过 |

## 9. 过程中遇到的问题

| 问题 | 原因 | 处理 |
| --- | --- | --- |
| `SQLite objects created in a thread can only be used in that same thread` | FastAPI 把同步依赖和同步路由放在线程池的不同线程 | 连接加 `check_same_thread=False`；每请求独立连接，单请求内顺序使用，sqlite3 默认串行模式安全 |
| 沙箱禁止 `Stop-Process`，无法启动再关闭真实服务做冒烟 | 策略限制 | 改用 ASGI `TestClient`：模板、路由、cookie、静态资源、重定向都覆盖，无需真实端口 |
| 两个依赖装不上 | 执行环境只放行 git 出网 | 用标准库实现签名会话与表单解析 |

## 10. 如何运行

```powershell
cd 'E:\knight hell'

# 演示数据（含两个账号的密码哈希）
uv run python src\flowremote\devtools\seed.py --reset --verify

# 启动浏览器界面
uv run uvicorn flowremote.api.app:app --reload --host 127.0.0.1 --port 8000

# 跑测试
uv run python -m unittest discover -s tests
```

然后打开 `http://127.0.0.1:8000`。

| 账号 | 密码 | 角色 | 能看到 |
| --- | --- | --- | --- |
| `alex.morgan@example.com` | `flowremote-demo` | operator | 只有 TASK-1001 |
| `admin@example.com` | `flowremote-demo` | admin | 全部任务 |

也可以直接在 `/signup` 注册新账号：新账号没有任何任务，首页显示 "No tasks yet"。

## 11. 安全说明与已知限制

- 演示密码写在 seed 里，仅用于本地演示；上线前必须删除演示账号并改为真实注册流程。
- 会话无法在服务端提前吊销（无会话表），退出只清 cookie；如需强制下线，后续可加会话表。
- 未启用 HTTPS；cookie 未加 `Secure`。部署时必须启用 HTTPS 并加上该属性。
- 没有登录失败次数限制（防暴力破解留在后续）。
- 明文密码只存在于请求内存中，不写日志。

## 12. 与课程要求的对应

| 要求 | 状态 |
| --- | --- |
| Working login | ✅ 注册、登录、登出、会话保持 |
| 第二个账号看不到第一个账号的数据 | ✅ 集成测试覆盖 |
| 权限角色（guest / user / admin） | ✅ guest 被挡、user 只看自己、admin 看全部 |
| Feature 1（复核 + 审批） | 未开始，P3/P4 |

## 13. 下一步

P3：在任务详情页加 Accept / Edit / Skip，写入 `decisions`（只增），让未决计数从 12 递减到 0，并把 `proceed_enabled` 显示在页面上。P4 再做审批页与 `approvals` 写入。
