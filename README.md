# My AI Agent

使用 DeepSeek、LangChain 和 LangGraph 的 Python 项目，需要 Python 3.13 或更高版本。

## 安装和运行

```powershell
uv sync --locked
```

在项目根目录的 `.env` 文件中配置 `DEEPSEEK_API_KEY`，然后运行：

```powershell
uv run my-ai-agent
```

也可以使用 `uv run python -m my_ai_agent`，或保留原来的 `uv run python src/main.py`。
输入 `exit` 退出。当前命令入口运行模型聊天；带工具的 Agent 工厂位于
`my_ai_agent.Agents.core.init_agent`。

## 项目结构

应用源码位于 `src/my_ai_agent/`，避免与第三方 `langchain` 包重名。
`Agents/` 存放 Agent，`LLM_init/` 初始化模型，`Tools/` 定义工具，
`Prompts/system.md` 存放系统提示词。

## 检查和构建

```powershell
uv lock --check
uv pip check
uv build
```
