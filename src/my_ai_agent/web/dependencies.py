from fastapi import Depends, Request

from .security import AuthContext, COOKIE_NAME, verify_csrf


def authenticated(request: Request) -> AuthContext:
    return request.app.state.auth.authenticate(request.cookies.get(COOKIE_NAME))


def authorized_write(request: Request, context: AuthContext = Depends(authenticated)):
    verify_csrf(context.csrf_token, request.headers.get("X-CSRF-Token"))
    return context
