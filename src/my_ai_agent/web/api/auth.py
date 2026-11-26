from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete

from ..dependencies import authenticated, authorized_write
from ..models import LoginSession
from ..schemas import LoginInput, PasswordInput
from ..security import AuthContext, COOKIE_NAME

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginInput, request: Request, response: Response):
    token, user = request.app.state.auth.login(payload.username, payload.password, request.client.host if request.client else "local")
    settings = request.app.state.settings
    secure = settings.cookie_secure if settings.cookie_secure is not None else request.url.scheme == "https"
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=secure, samesite="lax", max_age=settings.session_hours * 3600, path="/")
    return user


@router.get("/me")
def me(context: AuthContext = Depends(authenticated)):
    return {"id": context.user_id, "username": context.username, "csrf_token": context.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, context: AuthContext = Depends(authorized_write)):
    with request.app.state.database.session() as db:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == context.session_hash))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/password")
def password(payload: PasswordInput, request: Request, response: Response, context: AuthContext = Depends(authorized_write)):
    request.app.state.auth.change_password(context, payload.current_password, payload.new_password)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
