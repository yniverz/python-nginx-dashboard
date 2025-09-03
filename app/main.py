from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from app.web import static, views, api
from app.config import settings

PUBLIC_PATHS = {"/login"}
PUBLIC_PREFIXES = ("/static", "/api")

def create_app() -> FastAPI:
    app = FastAPI(title="Multi-Domain Edge Manager", root_path=settings.ROOT_PATH or "")


    @app.middleware("http")
    async def auth_and_flash(request: Request, call_next):
        # -- flash messages (your existing behavior) --
        flashes = request.session.pop("_flashes", [])
        request.state.flash_messages = flashes

        # -- auth gate --
        path = request.url.path
        is_public = (path in PUBLIC_PATHS) or path.startswith(PUBLIC_PREFIXES)
        logged_in = bool(request.session.get("user_id"))  # set this at login

        if not is_public and not logged_in:
            # If the client expects JSON, return 401; otherwise redirect to login
            accept = request.headers.get("accept", "")
            if "application/json" in accept:
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            return RedirectResponse(url=settings.ROOT_PATH + "/login", status_code=303)

        response = await call_next(request)
        return response

    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(views.router)
    app.include_router(api.router)
    app.include_router(static.router)

    
    return app

