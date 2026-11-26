import argparse
import getpass

import uvicorn

from .config import Settings
from .database import Database
from .security import AuthService


def serve():
    settings = Settings()
    uvicorn.run("my_ai_agent.web.app:create_app", factory=True, host="127.0.0.1", port=settings.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


def manage_user():
    parser = argparse.ArgumentParser(description="创建或重置本地 Web 账户。密码不会进入命令行参数。")
    parser.add_argument("action", choices=["create", "reset-password"])
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    password = getpass.getpass("密码（至少 12 位）: ")
    if password != getpass.getpass("再次输入密码: "):
        parser.error("两次密码不一致。")
    settings = Settings()
    settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = Database(settings.database_url)
    database.initialize()
    try:
        AuthService(database, settings).set_password(args.username, password, create=args.action == "create")
    except ValueError as exc:
        parser.error(str(exc))
    finally:
        database.engine.dispose()
    print("账户已创建。" if args.action == "create" else "密码已重置，旧会话已失效。")
