from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api import auth, conversations, runs, system
from .config import Settings
from .database import Database
from .security import AuthService
from .services.conversations import ConversationService
from .services.runtime import AgentRuntime


def create_app(settings: Settings | None = None, *, agent_factory=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        load_dotenv()
        settings.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        database = Database(settings.database_url)
        database.initialize()
        app.state.database = database
        app.state.settings = settings
        app.state.auth = AuthService(database, settings)
        app.state.conversations = ConversationService(database)
        async with AsyncSqliteSaver.from_conn_string(str(settings.data_dir.resolve() / "checkpoints.sqlite3")) as saver:
            await saver.setup()
            runtime = AgentRuntime(database, saver, settings, agent_factory)
            runtime.recover()
            app.state.runtime = runtime
            try:
                yield
            finally:
                await runtime.shutdown()
        database.engine.dispose()

    app = FastAPI(title="Agent Studio API", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Validation responses must not echo password or message input values.
        return JSONResponse({"detail": [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in exc.errors()]}, status_code=422)

    @app.middleware("http")
    async def request_guards(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
            expected = str(request.base_url).rstrip("/")
            allowed = {expected}
            if settings.public_origin:
                allowed.add(settings.public_origin.rstrip("/"))
            if origin.rstrip("/") not in allowed:
                return JSONResponse({"detail": "请求来源不受信任。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        return response

    for router in (auth.router, conversations.router, runs.router, system.router):
        app.include_router(router, prefix="/api")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        root = settings.frontend_dist.resolve()
        target = (root / path).resolve()
        if path == "api" or path.startswith("api/") or not target.is_relative_to(root):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        if "." in target.name or not (root / "index.html").is_file():
            raise HTTPException(404, "前端尚未构建，请运行 npm run build。")
        return FileResponse(root / "index.html")

    return app
