# Web 工作台架构

前端采用 Vue 3、TypeScript、Vite、Vue Router 和 Pinia。后端采用 FastAPI，保留原有 CLI。
这是模块化单体：认证、会话、执行和前端组件分别演进，暂不引入微服务、Redis 或 WebSocket。

```text
Browser (Vue SPA)
        │ HTTPS, same origin
      Nginx
        ├── /        frontend/dist
        └── /api/*   HTTP → 127.0.0.1:8000 (FastAPI)
                          ├── api/             HTTP 参数与响应
                          ├── security.py      账户、会话与密码哈希
                          ├── services/        会话管理与运行编排
                          ├── models.py        数据模型
                          └── Agent + Tools    原有 Agent 核心
```

## 通信与事件

普通资源使用 JSON HTTP 接口，发送消息使用 `POST /api/conversations/{id}/runs`。
该请求返回 SSE；前端通过 fetch 读取 HTTP 流，因此可以携带 Cookie、CSRF 头和 POST 请求体。
停止任务使用独立 POST 接口，无需 WebSocket。Nginx 需关闭 SSE 缓冲。

| 事件 | 含义 |
| --- | --- |
| `run.started` | 返回运行 ID 和助手消息 ID |
| `message.delta` | 模型正文的增量文本 |
| `tool.started` | 工具名、参数、运行时间 |
| `tool.completed` | 工具结果和成功/失败状态 |
| `run.completed` / `run.failed` / `run.cancelled` | 任务终态 |

前端将模型回答与工具记录分开展示。Markdown 通过 DOMPurify 清理后渲染。
SSE 接口发送 `X-Accel-Buffering: no`，并发送心跳维持连接。

## 账户与权限

- 账户在本机 CLI 创建，不提供公开注册，也没有默认密码。
- 密码使用 Argon2 哈希；浏览器使用 HttpOnly、SameSite=Lax Cookie，不在 localStorage 保存令牌。
- 数据库只保存登录令牌的 SHA-256 摘要，支持退出、过期和改密码撤销所有登录。
- 已登录的写操作需要 CSRF 请求头；变更请求检查 Origin，后端校验 Host。
- 登录有单进程的按客户端限速。生产仅信任来自本机 Nginx 的代理头。
- 用户只能读取或修改自己的会话；Agent 记忆按用户和会话 ID 隔离。

账户隔离针对聊天记录，不是操作系统沙箱。所有 Web 账户都是受信任的主机操作者，工具仍使用后端进程的 OS 权限。
管理员提权、系统审批和不可信租户隔离尚未接入；将来应接到服务层的执行请求与事件接口。

## 持久化与生命周期

SQLAlchemy 管理 `.agent-data/app.sqlite3` 中的用户、登录、会话、消息、运行和上下文归档。
LangGraph 将 Web 当前模型窗口写入 `checkpoints.sqlite3`，将 CLI 窗口写入 `cli-checkpoints.sqlite3`。
重启后两种入口都能继续原会话。备份时同时保留对应的数据文件和附件目录。

Agent 从 DeepSeek `/models` 读取模型窗口和输出上限，扣除当前思考档位需要的输出空间及 10% 的估算余量。
每次模型调用前，Agent 对照预算估算当前请求，先将旧工具输出换成带记录 ID 的预览，
再按需要生成摘要。摘要替换已经配对的旧消息区间，保留最近原文和当前用户请求。
服务明确返回上下文超限时，可以缩小窗口后只重试模型调用一次。
摘要、原始消息和工具已经返回的输出按会话保存在 `context_records`。
搜索按字面关键词匹配，按命中偏移量分页回读。删除 Web 会话会同时清理对应的归档和 LangGraph 状态。

Agent 按需初始化，因此未配置模型也能启动服务、登录和管理账户。
单个会话同时只允许一个任务；默认全局最多两个，使用 `AGENT_MAX_PARALLEL_RUNS` 配置。
默认运行一个 Uvicorn worker：活动任务、限速和取消控制在进程内。扩展多进程前，需将这些状态迁移到共享存储/任务执行服务。
数据库目前用 `create_all` 初始化第一版表结构；后续变更持久化结构时应加入版本化迁移。

浏览器断开 SSE 会取消 Agent 后续运行，已完成或部分回复在正常退出时保存。
取消不能撤销已执行的文件或命令操作；运行中的同步 Shell 工具可能继续到其自身超时。
进程异常退出时，任务下次启动被标为 interrupted；异常退出前尚未落盘的输出可能丢失。

## 扩展位置

- 新的工具：`Tools/` 实现并在 `TOOLS` 注册，Web 工具目录自动更新。
- 新的 UI：按业务在 `frontend/src/views`、`components`、`stores` 和 `api` 扩展。
- 新的 HTTP 能力：`web/api` 路由调用 `web/services`，不要把业务逻辑堆进 app.py。
- 新的运行事件：后端 runtime 和前端 types.ts/SSE 消费逻辑同步扩展。
- 新的模型或权限执行器：接入 Agent factory 或执行服务，HTTP 路由不直接处理 OS 提权。
