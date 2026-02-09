"""
API endpoints for external services.
Provides configuration endpoints for FRP gateway servers and clients.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.persistence.db import get_db, ensure_schema
from app.persistence import repos
from app.services.frp import generate_server_toml, generate_client_toml

router = APIRouter(prefix="/api")

# Ensure database tables exist and apply migrations
ensure_schema()

@router.get("/gateway/server/{server_id}", response_class=PlainTextResponse)
def get_gateway_server(server_id: str, request: Request, db: Session = Depends(get_db), x_gateway_token: str | None = Header(None)):
    """
    Get FRP server configuration for a gateway server.
    Requires X-Gateway-Token header for authentication.
    """
    # Access request domain information
    host = request.headers.get("host")  # Gets the Host header which includes domain:port
    
    # Get the base request URI without query parameters
    scheme = request.url.scheme  # http or https
    path = request.url.path  # The path component of the URL
    
    # Construct the full URI without query parameters
    base_uri = f"{scheme}://{host}{path}"
    
    # Validate authentication token
    if not x_gateway_token:
        raise HTTPException(status_code=404)

    server = repos.GatewayServerRepo(db).by_name(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Gateway server not found")

    if x_gateway_token != server.auth_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Update last config pull time and URL
    server.last_config_pull_time = datetime.now(timezone.utc)
    server.last_config_pull_url = base_uri
    db.commit()

    return PlainTextResponse(generate_server_toml(server))

@router.get("/gateway/client/{client_id}", response_class=PlainTextResponse)
def get_gateway_client(client_id: str, request: Request, db: Session = Depends(get_db), x_gateway_token: str | None = Header(None)):
    """
    Get FRP client configuration for a gateway client.
    Requires X-Gateway-Token header for authentication.
    """
    # Access request domain information
    host = request.headers.get("host")  # Gets the Host header which includes domain:port
    
    # Get the base request URI without query parameters
    scheme = request.url.scheme  # http or https
    path = request.url.path  # The path component of the URL
    
    # Construct the full URI without query parameters
    base_uri = f"{scheme}://{host}{path}"
    
    # Validate authentication token
    if not x_gateway_token:
        raise HTTPException(status_code=404)

    client = repos.GatewayClientRepo(db).by_name(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Gateway client not found")

    if x_gateway_token != client.server.auth_token:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Update last config pull time and URL
    client.last_config_pull_time = datetime.now(timezone.utc)
    client.last_config_pull_url = base_uri
    db.commit()

    return PlainTextResponse(generate_client_toml(db, client))
