from langchain_core.messages import AIMessage

from my_ai_agent.Agents.core import init_agent

def main() -> None:
    try:
        agent = init_agent()
    except Exception as e:
        print("错误:",e)
        return
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


if __name__ == "__main__":
    main()
