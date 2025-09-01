from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.db import engine
from app.models import Base
from app.routers import admin, domains, http_routes, stream_routes, dns

def create_app() -> FastAPI:
    # create DB tables on boot (no external DB server)
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title="multi-domain-proxy")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(admin.router)
    app.include_router(domains.router)
    app.include_router(http_routes.router)
    app.include_router(stream_routes.router)
    app.include_router(dns.router)
    return app
