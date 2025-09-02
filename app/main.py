from uuid import uuid4
from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from app.web import views#, api

def create_app() -> FastAPI:
    app = FastAPI(title="Multi-Domain Edge Manager")
    @app.middleware("http")
    async def load_flash_messages(request: Request, call_next):
        # Pop any pending flashes at the start of the request
        flashes = request.session.pop("_flashes", [])
        request.state.flash_messages = flashes
        response = await call_next(request)
        return response
    app.add_middleware(SessionMiddleware, secret_key=uuid4().hex)
    # app.include_router(api.router)
    app.include_router(views.router)
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

    
    return app

