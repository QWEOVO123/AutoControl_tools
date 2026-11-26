from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver

from my_ai_agent.Agents.context_archive import ContextArchive
from my_ai_agent.Agents.core import init_agent
from my_ai_agent.web.config import Settings
from my_ai_agent.web.database import Database


def chat(agent) -> None:
    config = {"configurable": {"thread_id": "cli"}}
    while True:
        try:
            text = input("\n用户:").strip()
        except(KeyboardInterrupt,EOFError):
            print("已退出\n")
            break
        if text.lower() == "exit":
            break
        if not text:
            continue
        print("AI: ", end="", flush=True)
        try:
            for chunk, metadata in agent.stream(
                    {"messages": [{"role": "user", "content": text}]},
                    config=config,
                    stream_mode="messages",
            ):
                # 只展示模型消息
                if not isinstance(chunk, AIMessage):
                    continue

                for block in chunk.content_blocks:
                    if block["type"] == "text":
                        print(block["text"], end="", flush=True)

            print()
        except Exception as e:
            print("\nAgent 执行失败，原因:", e)


def main() -> None:
    settings = Settings()
    settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = Database(settings.database_url)
    try:
        database.initialize()
        with SqliteSaver.from_conn_string(str(settings.data_dir / "cli-checkpoints.sqlite3")) as saver:
            try:
                agent = init_agent(
                    checkpointer=saver, archive=ContextArchive(database),
                    context_token_budget=settings.context_token_budget, context_keep_tokens=settings.context_keep_tokens,
                )
            except Exception as error:
                print("错误:", error)
                return
            chat(agent)
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
