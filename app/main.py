"""
Main FastAPI application factory and middleware configuration.
Handles authentication, session management, and route registration.
"""
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from app.web import static, views, api
from app.config import settings

# Paths that don't require authentication
PUBLIC_PATHS = {"/login"}
PUBLIC_PREFIXES = ("/static", "/api")

def create_app() -> FastAPI:
    """Create and configure the FastAPI application with middleware and routes."""
    app = FastAPI(title="Multi-Domain Edge Manager", root_path=settings.ROOT_PATH or "")

    @app.middleware("http")
    async def auth_and_flash(request: Request, call_next):
        """
        Middleware that handles authentication and flash message management.
        - Extracts flash messages from session and makes them available to templates
        - Enforces authentication for protected routes
        - Returns appropriate responses for JSON vs HTML clients
        """
        # Extract flash messages from session and attach to request state
        flashes = request.session.pop("_flashes", [])
        request.state.flash_messages = flashes

        # Check if the current path requires authentication
        path = request.url.path
        is_public = (path in PUBLIC_PATHS) or path.startswith(PUBLIC_PREFIXES)
        logged_in = bool(request.session.get("user_id"))

        if not is_public and not logged_in:
            # Return 401 for JSON clients, redirect for HTML clients
            accept = request.headers.get("accept", "")
            if "application/json" in accept:
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            return RedirectResponse(url=settings.ROOT_PATH + "/login", status_code=303)

        response = await call_next(request)
        return response

    # Add session middleware with secure secret key
    app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET or str(uuid4()))
    
    # Register all route modules
    app.include_router(views.router)
    app.include_router(api.router)
    app.include_router(static.router)

    return app

