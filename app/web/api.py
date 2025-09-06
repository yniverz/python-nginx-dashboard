"""
API endpoints for external services.
Provides configuration endpoints for FRP gateway servers and clients.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.persistence.db import get_db, Base, engine
from app.persistence import repos
from app.services.frp import generate_server_toml, generate_client_toml

router = APIRouter(prefix="/api")

# Ensure database tables exist
Base.metadata.create_all(bind=engine)

@router.get("/gateway/server/{server_id}", response_class=PlainTextResponse)
def get_gateway_server(server_id: str, db: Session = Depends(get_db), x_gateway_token: str | None = Header(None)):
    """
    Get FRP server configuration for a gateway server.
    Requires X-Gateway-Token header for authentication.
    """
    # Validate authentication token
    if not x_gateway_token:
        raise HTTPException(status_code=404)

    server = repos.GatewayServerRepo(db).by_name(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Gateway server not found")

    if x_gateway_token != server.auth_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Update last config pull time
    server.last_config_pull_time = datetime.now(timezone.utc)
    db.commit()

    return PlainTextResponse(generate_server_toml(server))

@router.get("/gateway/client/{client_id}", response_class=PlainTextResponse)
def get_gateway_client(client_id: str, db: Session = Depends(get_db), x_gateway_token: str | None = Header(None)):
    """
    Get FRP client configuration for a gateway client.
    Requires X-Gateway-Token header for authentication.
    """
    # Validate authentication token
    if not x_gateway_token:
        raise HTTPException(status_code=404)

    client = repos.GatewayClientRepo(db).by_name(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Gateway client not found")

    if x_gateway_token != client.server.auth_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Update last config pull time
    client.last_config_pull_time = datetime.now(timezone.utc)
    db.commit()

    return PlainTextResponse(generate_client_toml(db, client))
