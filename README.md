# My AI Agent

使用 DeepSeek、LangChain 和 LangGraph 的 Python 项目，需要 Python 3.13 或更高版本。

现包含独立的 Vue 3 Web 工作台与 FastAPI 后端：账户登录、会话历史、流式回答、工具执行记录和账户设置。

## Web 工作台

在项目根目录执行：

```powershell
uv sync --locked
uv run my-ai-agent-user create --username admin
```

命令会以隐藏输入的方式询问密码，至少 12 位；没有默认账户或默认密码。
在本地 `.env` 中设置 `DEEPSEEK_API_KEY`，不要将真实密钥写入 `.env.example`。

构建前端（需要受当前 Vite 支持的 Node.js，推荐 Node 24 LTS）：

```powershell
cd frontend
npm ci
npm run build
cd ..
uv run my-ai-agent-web
```

打开 <http://127.0.0.1:8000>。后端仅监听 `127.0.0.1`，构建后也能直接提供前端文件。
如忘记密码，在本机执行 `uv run my-ai-agent-user reset-password --username admin`。

前端开发时，在项目根目录启动后端，再在 `frontend/` 中运行 `npm run dev`。
访问 Vite 输出的本机地址，`/api` 自动代理到 8000 端口。

生产使用 [Nginx 配置示例](deploy/nginx.conf.example)，前后端同源提供 HTTPS。
在本机 `.env` 配置 `AGENT_ALLOWED_HOSTS=["实际域名"]`、`AGENT_PUBLIC_ORIGIN=https://实际域名`
和 `AGENT_COOKIE_SECURE=true`。Nginx 的工作是终止 HTTPS、提供静态文件并转发 `/api`，SSE 缓冲必须关闭。
数据默认保存在被 Git 忽略的 `.agent-data/` 中，API Key 只在后端环境中加载。

详细模块说明、事件协议和运行边界见 [Web 架构文档](docs/web-architecture.md)。
Web 账户可执行本机工具，只向受信任的操作者开放；目前未提供系统沙箱或管理员提权。

Web 输入框可以添加附件或直接粘贴截图，支持 `deepseek-flash`。每条消息最多 4 个文件，每个最多 12 MiB。
附件在发送后上传至 DeepSeek，保留在所属会话中，便于继续追问。文件引用接近过期时会用本地副本续期。
输入框的花括号按钮可启用 JSON 输出。回答下方显示上游提供的 Token 用量和缓存命中，也可以请求朗读。
「文字与语音识别」支持图片或文档 OCR，以及 PCM WAV / Ogg Opus 文件转写。
「设置与工具 → 背景与外观」支持自选背景图和恢复默认，图片保存在当前浏览器。

Web 和 CLI 都支持长会话。接近输入预算时，Agent 先缩短较早的工具输出，仍超预算时把旧历史整理成摘要检查点。
模型可以用 `context_search` 在当前会话按关键词找检查点、消息或日志，再用 `context_read` 按记录 ID 分页回读。
Agent 初始化时从 DeepSeek 的 `/models` 读取模型窗口和输出上限。压缩阈值按窗口减去本次思考档位预留的输出和 10% 余量计算。
元数据不可用时使用 120,000 Token 的估算输入预算。`AGENT_CONTEXT_TOKEN_BUDGET` 可设置更早压缩的输入上限，
`AGENT_CONTEXT_KEEP_TOKENS` 可调整近期原文保留目标（默认 16,000 Token）。

## 安装和运行

```powershell
uv sync --locked
```

在项目根目录的 `.env` 文件中配置 `DEEPSEEK_API_KEY`，然后运行：

```powershell
uv run my-ai-agent
```

也可以使用 `uv run python -m my_ai_agent`，或保留原来的 `uv run python src/main.py`。
输入 `exit` 退出。当前命令入口运行带工具和会话记忆的 Agent；Agent 工厂位于
`my_ai_agent.Agents.core.init_agent`。

## 项目结构

应用源码位于 `src/my_ai_agent/`，避免与第三方 `langchain` 包重名。
`Agents/` 存放 Agent，`LLM_init/` 初始化模型，`Tools/` 定义工具，
`Prompts/system.md` 存放系统提示词。

## 本地工具

| 工具 | 用途 |
| --- | --- |
| `execute_shell` | 执行非交互命令，返回 stdout、stderr、退出码和超时状态 |
| `web_search` / `web_fetch` | 通过 DeepSeek 检索公开网页或读取链接正文，工具记录中可查看来源 |
| `job_start` / `job_output` / `job_cancel` | 启动、查询和取消后台任务。任务超时可自定，设为 null 时持续运行。输出支持按游标续读 |
| `context_search` / `context_read` | 当前会话的关键词检索和原文回读，覆盖检查点、消息和已归档的工具输出 |
| `sleep` | 定时暂停当前 Agent，唤醒时返回实际等待时长和传入的上下文 |
| `math_compute` | 算术、实数函数、数论、组合、统计、位运算、进制和线性代数。用 `operation="list"` 查看目录 |
| `execute_python` | 用项目 Python 解释器执行临时脚本，支持参数、后台执行与输出续读 |
| `list_directory` | 查看目录直接子项 |
| `find_files` | 按 glob 检索文件名 |
| `search_text` | 按字面文本或 Python 正则搜索文件内容，返回行号 |
| `read_file` | 分段读取 UTF-8 文本，输出带行号 |
| `write_file` | 创建文件，默认拒绝覆盖 |
| `edit_file` | 精确替换，默认要求唯一匹配，保留 BOM 和换行风格 |
| `get_current_time` / `get_system_info` / `multiply` | 时间、环境和乘法 |

例如可以问：“找出模型初始化代码，说明调用流程”“运行 uv pip check”
或“新建一个计算函数并运行验证”。相对路径基于启动命令所在目录。

Windows Shell 优先使用 `pwsh`，否则使用 Windows PowerShell；其它系统使用 `/bin/sh`。
前台 `execute_shell` 每次调用独立，默认超时 30 秒，最多 120 秒。超时会尝试终止进程树。
输出分别限制 stdout/stderr 长度，进程不接受交互输入。
后台任务限当前会话访问，状态和输出保存在当前后端进程中。每路输出保留最近的 256,000 字符，可分页读取。
Web 停止生成会取消当前的 `sleep` 等待，后台任务可用 `job_cancel` 单独停止。后端重启后，等待不会恢复。

文件检索跳过凭据、常见缓存、虚拟环境和符号链接，不依赖额外安装 ripgrep。
文本读取限 UTF-8、单文件最多 1 MiB；大文件或二进制文件需要专门处理。
专用文件工具拒绝访问 `.env`、私钥、`secrets/` 和 Git 内部数据，`.env.example` 可读写。
Shell 以当前用户权限运行；这些文件过滤和提示词约定不构成 Shell 沙箱或程序级审批机制。

提示词参考 [OpenCode 公开提示词](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/plugin/system-prompt/meta.txt)
和 [工具文档](https://opencode.ai/docs/tools/)，按本项目实际工具重写，涵盖先调查后修改、专用工具优先、结果验证和凭据保护。
Agent 初始化时还会加入实际工作目录、操作系统和 Python 解释器信息。

## 检查和构建

```powershell
uv lock --check
uv pip check
uv build
uv run python -m unittest discover -s tests -v
```

前端检查：在 `frontend/` 中运行 `npm test` 和 `npm run build`。
