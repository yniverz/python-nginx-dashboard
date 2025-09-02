from datetime import datetime
import traceback
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.persistence.db import SessionLocal, Base, engine
from app.persistence import repos
from app.persistence.models import (
    Domain, GatewayClient, GatewayConnection, GatewayFlag, GatewayProtocol, GatewayServer, NginxRoute,
    DnsRecord, ManagedBy, NginxRouteHost, NginxRouteProtocol
)

templates = Jinja2Templates(directory="app/web/templates")
router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

Base.metadata.create_all(bind=engine)


def flash(request: Request, message: str, category: str = "info") -> None:
    # Store messages in session (list of dicts)
    bucket = request.session.get("_flashes", [])
    bucket.append({"message": message, "category": category})
    request.session["_flashes"] = bucket



@router.get("/", response_class=HTMLResponse)
def view_dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("dashboard.jinja2", {"request": request})





###################################################
#                     Domains                     #
###################################################

@router.get("/domains", response_class=HTMLResponse)
def view_domains(request: Request, db: Session = Depends(get_db)):
    domains = repos.DomainRepo(db).list_all()
    return templates.TemplateResponse("domains.jinja2", {"request": request, "domains": domains})

@router.post("/domains/create", response_class=RedirectResponse)
async def create_domain(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        repos.DomainRepo(db).create(
            Domain(
                name=form["name"],
                zone_id=form["zone_id"]
            )
        )
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error creating domain: {str(e)}", category="error")

    return RedirectResponse(url="/domains", status_code=303)


@router.get("/domains/edit/{domain_id}/{action}", response_class=RedirectResponse)
async def edit_domain(request: Request, domain_id: int, action: str, db: Session = Depends(get_db)):
    try:
        if action == "toggle_auto_wildcard":
            # Toggle the auto_wildcard setting
            domain = repos.DomainRepo(db).get(domain_id)
            if domain:
                domain.auto_wildcard = not domain.auto_wildcard
                repos.DomainRepo(db).update(domain)
        elif action == "toggle_use_for_direct_prefix":
            # Toggle the use_for_direct_prefix setting
            domain = repos.DomainRepo(db).get(domain_id)
            if domain:
                domain.use_for_direct_prefix = not domain.use_for_direct_prefix
                repos.DomainRepo(db).update(domain)
        elif action == "delete":
            repos.DomainRepo(db).delete(domain_id)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error updating domain: {str(e)}", category="error")
    return RedirectResponse(url="/domains", status_code=303)





###################################################
#                     Proxies                     #
###################################################

@router.get("/proxies", response_class=HTMLResponse)
def view_proxies(request: Request, db: Session = Depends(get_db)):
    servers = repos.GatewayServerRepo(db).list_all()
    clients = repos.GatewayClientRepo(db).list_all()
    connections = repos.GatewayConnectionRepo(db).list_all()
    return templates.TemplateResponse("proxies.jinja2", {"request": request, "servers": servers, "clients": clients, "connections": connections, "now": datetime.now()})


@router.post("/proxies/create/{proxy_type}", response_class=RedirectResponse)
async def create_proxy(request: Request, proxy_type: str, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        if proxy_type == "server":
            repos.GatewayServerRepo(db).create(
                GatewayServer(
                    name=form["name"],
                    host=form["host"],
                    bind_port=form["bind_port"],
                    auth_token=form["auth_token"]
                )
            )
        elif proxy_type == "client":
            repos.GatewayClientRepo(db).create(
                GatewayClient(
                    name=form["name"],
                    server_id=form["server_id"]
                )
            )
        elif proxy_type == "connection":
            repos.GatewayConnectionRepo(db).create(
                GatewayConnection(
                    name=form["name"],
                    client_id=form["client_id"],
                    protocol=form["protocol"],
                    local_ip=form["local_ip"],
                    local_port=form["local_port"],
                    remote_port=form["remote_port"]
                )
            )
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error creating proxy: {str(e)}", category="error")

    return RedirectResponse(url="/proxies", status_code=303)


################################
#            Server            #
################################

@router.get("/proxies/edit/server/{server_id}", response_class=HTMLResponse)
def edit_proxy_server(request: Request, server_id: int, db: Session = Depends(get_db)):
    server = repos.GatewayServerRepo(db).get(server_id)
    if not server:
        flash(request, "Server not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)
    return templates.TemplateResponse("proxies.edit.server.jinja2", {"request": request, "server": server})

@router.post("/proxies/edit/server/{server_id}", response_class=RedirectResponse)
async def update_proxy_server(request: Request, server_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    server = repos.GatewayServerRepo(db).get(server_id)
    if not server:
        flash(request, "Server not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    try:
        server.name = form["name"]
        server.host = form["host"]
        server.bind_port = form["bind_port"]
        server.auth_token = form["auth_token"]
        server.is_origin = form.get("is_origin", "off") == "on"
        repos.GatewayServerRepo(db).update(server)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error updating server: {str(e)}", category="error")

    return RedirectResponse(url="/proxies", status_code=303)

@router.post("/proxies/delete/server/{server_id}", response_class=RedirectResponse)
async def delete_proxy_server(request: Request, server_id: int, db: Session = Depends(get_db)):
    server = repos.GatewayServerRepo(db).get(server_id)
    if not server:
        flash(request, "Server not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    if any(client.server_id == server.id for client in repos.GatewayClientRepo(db).list_all()):
        flash(request, "Server has active clients and cannot be deleted", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    try:
        repos.GatewayServerRepo(db).delete(server.id)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error deleting server: {str(e)}", category="error")

    return RedirectResponse(url="/proxies", status_code=303)



################################
#            Clients           #
################################

@router.get("/proxies/edit/client/{client_id}", response_class=HTMLResponse)
def edit_proxy_client(request: Request, client_id: int, db: Session = Depends(get_db)):
    client = repos.GatewayClientRepo(db).get(client_id)
    if not client:
        flash(request, "Client not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)
    return templates.TemplateResponse("proxies.edit.client.jinja2", {"request": request, "client": client})

@router.post("/proxies/edit/client/{client_id}", response_class=RedirectResponse)
async def update_proxy_client(request: Request, client_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    client = repos.GatewayClientRepo(db).get(client_id)
    if not client:
        flash(request, "Client not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    try:
        client.name = form["name"]
        client.server_id = form["server_id"]
        repos.GatewayClientRepo(db).update(client)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error updating client: {str(e)}", category="error")

    return RedirectResponse(url="/proxies", status_code=303)

@router.post("/proxies/delete/client/{client_id}", response_class=RedirectResponse)
async def delete_proxy_client(request: Request, client_id: int, db: Session = Depends(get_db)):
    client = repos.GatewayClientRepo(db).get(client_id)
    if not client:
        flash(request, "Client not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    if any(conn.client_id == client.id for conn in repos.GatewayConnectionRepo(db).list_all()):
        flash(request, "Client has active connections and cannot be deleted", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    try:
        repos.GatewayClientRepo(db).delete(client.id)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error deleting client: {str(e)}", category="error")

    return RedirectResponse(url="/proxies", status_code=303)




################################
#         Connections          #
################################

@router.get("/proxies/edit/connection/{connection_id}", response_class=HTMLResponse)
def edit_proxy_connection(request: Request, connection_id: int, db: Session = Depends(get_db)):
    connection = repos.GatewayConnectionRepo(db).get(connection_id)
    if not connection:
        flash(request, "Connection not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)
    # get clients, protocols, flags
    clients = repos.GatewayClientRepo(db).list_all()
    # protocols = list(GatewayProtocol)
    # flags = list(GatewayFlag)
    protocols = [e.value for e in GatewayProtocol]
    flags = [e.value for e in GatewayFlag]
    print(connection.flags)
    return templates.TemplateResponse("proxies.edit.connection.jinja2", {"request": request, "connection": connection, "clients": clients, "protocols": protocols, "flags": flags})

@router.post("/proxies/edit/connection/{connection_id}", response_class=RedirectResponse)
async def update_proxy_connection(request: Request, connection_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    connection = repos.GatewayConnectionRepo(db).get(connection_id)
    if not connection:
        flash(request, "Connection not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    try:
        connection.name = form["name"]
        connection.client_id = form["client_id"]
        connection.protocol = form["protocol"]
        connection.local_ip = form["local_ip"]
        connection.local_port = form["local_port"]
        connection.remote_port = form["remote_port"]

        flags = [v for k, v in form.items() if k.startswith("flag_")]
        connection.flags = flags

        repos.GatewayConnectionRepo(db).update(connection)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error updating connection: {str(e)}", category="error")

    return RedirectResponse(url="/proxies", status_code=303)

@router.post("/proxies/delete/connection/{connection_id}", response_class=RedirectResponse)
async def delete_proxy_connection(request: Request, connection_id: int, db: Session = Depends(get_db)):
    connection = repos.GatewayConnectionRepo(db).get(connection_id)
    if not connection:
        flash(request, "Connection not found", category="error")
        return RedirectResponse(url="/proxies", status_code=303)

    try:
        repos.GatewayConnectionRepo(db).delete(connection.id)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error deleting connection: {str(e)}", category="error")

    return RedirectResponse(url="/proxies", status_code=303)





###################################################
#                     Routes                      #
###################################################

@router.get("/routes", response_class=HTMLResponse)
def list_routes(request: Request, db: Session = Depends(get_db)):
    routes = repos.NginxRouteRepo(db).list_all()
    domains = repos.DomainRepo(db).list_all()
    protocols = [e.value for e in NginxRouteProtocol]

    routes.sort(key=lambda r: (r.domain_id, r.subdomain.split(".")[::-1]))

    return templates.TemplateResponse("routes.jinja2", {"request": request, "routes": routes, "domains": domains, "protocols": protocols})


@router.post("/routes/create", response_class=RedirectResponse)
async def create_route(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        repos.NginxRouteRepo(db).create(
            NginxRoute(
                domain_id=form["domain_id"],
                subdomain=form["subdomain"],
                protocol=form["protocol"],
                path_prefix=form.get("path_prefix", "/") or "/",
                backend_path=form.get("backend_path", "") or "",
            )
        )
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error creating route: {str(e)}", category="error")

    return RedirectResponse(url="/routes", status_code=303)

@router.get("/routes/edit/{route_id}", response_class=HTMLResponse)
async def edit_route(request: Request, route_id: int, db: Session = Depends(get_db)):
    route = repos.NginxRouteRepo(db).get(route_id)
    if not route:
        flash(request, "Route not found", category="error")
        return RedirectResponse(url="/routes", status_code=303)

    domains = repos.DomainRepo(db).list_all()
    protocols = [e.value for e in NginxRouteProtocol]

    return templates.TemplateResponse("routes.edit.jinja2", {"request": request, "route": route, "domains": domains, "protocols": protocols})

@router.get("/routes/edit/{route_id}/toggle_active", response_class=RedirectResponse)
async def toggle_route(request: Request, route_id: int, db: Session = Depends(get_db)):
    route = repos.NginxRouteRepo(db).get(route_id)
    if not route:
        flash(request, "Route not found", category="error")
        return RedirectResponse(url="/routes", status_code=303)

    try:
        route.active = not route.active
        repos.NginxRouteRepo(db).update(route)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error toggling route: {str(e)}", category="error")

    return RedirectResponse(url="/routes", status_code=303)

@router.post("/routes/edit/{route_id}", response_class=RedirectResponse)
async def update_route(request: Request, route_id: int, db: Session = Depends(get_db)):
    route = repos.NginxRouteRepo(db).get(route_id)
    if not route:
        flash(request, "Route not found", category="error")
        return RedirectResponse(url="/routes", status_code=303)

    form = await request.form()
    try:
        route.domain_id = form["domain_id"]
        route.subdomain = form["subdomain"]
        route.protocol = form["protocol"]
        route.path_prefix = form.get("path_prefix", "/") or "/"
        route.backend_path = form.get("backend_path", "") or ""
        repos.NginxRouteRepo(db).update(route)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error updating route: {str(e)}", category="error")

    return RedirectResponse(url="/routes", status_code=303)

@router.get("/routes/delete/{route_id}", response_class=RedirectResponse)
async def delete_route(request: Request, route_id: int, db: Session = Depends(get_db)):
    try:
        repos.NginxRouteRepo(db).delete(route_id)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error deleting route: {str(e)}", category="error")

    return RedirectResponse(url="/routes", status_code=303)



################################
#         Connections          #
################################


@router.post("/routes/edit/{route_id}/hosts/create", response_class=RedirectResponse)
async def create_host(request: Request, route_id: int, db: Session = Depends(get_db)):
    form = await request.form()

    route = repos.NginxRouteRepo(db).get(route_id)
    if not route:
        flash(request, "Route not found", category="error")
        return RedirectResponse(url="/routes", status_code=303)

    try:
        host = NginxRouteHost(
            route_id=route_id,
            host=form["host"],
            weight=int(form["weight"]) if form.get("weight") else None,
            max_fails=int(form["max_fails"]) if form.get("max_fails") else None,
            fail_timeout=int(form["fail_timeout"]) if form.get("fail_timeout") else None,
            is_backup=form.get("is_backup", "off") == "on",
            active=form.get("active", "off") == "on"
        )
        route.hosts.append(host)
        repos.NginxRouteRepo(db).update(route)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error creating host: {str(e)}", category="error")

    return RedirectResponse(url=f"/routes/edit/{route_id}", status_code=303)

@router.get("/routes/edit/{route_id}/hosts/{host_id}/toggle_active", response_class=RedirectResponse)
async def toggle_host(request: Request, route_id: int, host_id: int, db: Session = Depends(get_db)):
    route = repos.NginxRouteRepo(db).get(route_id)
    if not route:
        flash(request, "Route not found", category="error")
        return RedirectResponse(url="/routes", status_code=303)

    host = next((h for h in route.hosts if h.id == host_id), None)
    if not host:
        flash(request, "Host not found", category="error")
        return RedirectResponse(url=f"/routes/edit/{route_id}", status_code=303)

    try:
        host.active = not host.active
        repos.NginxRouteRepo(db).update(route)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error toggling host: {str(e)}", category="error")

    return RedirectResponse(url=f"/routes/edit/{route_id}", status_code=303)

@router.post("/routes/edit/{route_id}/hosts/{host_id}/delete", response_class=RedirectResponse)
async def delete_host(request: Request, route_id: int, host_id: int, db: Session = Depends(get_db)):
    form = await request.form()

    route = repos.NginxRouteRepo(db).get(route_id)
    if not route:
        flash(request, "Route not found", category="error")
        return RedirectResponse(url="/routes", status_code=303)

    host = next((h for h in route.hosts if h.id == host_id), None)
    if not host:
        flash(request, "Host not found", category="error")
        return RedirectResponse(url=f"/routes/edit/{route_id}", status_code=303)

    try:
        route.hosts.remove(host)
        repos.NginxRouteRepo(db).update(route)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error deleting host: {str(e)}", category="error")

    return RedirectResponse(url=f"/routes/edit/{route_id}", status_code=303)






###################################################
#                      DNS                        #
###################################################

@router.get("/dns", response_class=HTMLResponse)
async def list_dns(request: Request, db: Session = Depends(get_db)):
    dns_records = repos.DnsRecordRepo(db).list_all()
    domains = repos.DomainRepo(db).list_all()

    dns_records.sort(key=lambda r: (r.domain.name, r.name.split(".")[::-1]))

    return templates.TemplateResponse("dns.jinja2", {"request": request, "dns_records": dns_records, "domains": domains})

@router.post("/dns/create", response_class=RedirectResponse)
async def create_dns_record(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        dns_record = DnsRecord(
            name=form["name"],
            domain_id=form["domain_id"],
            type=form["type"],
            content=form["content"],
            ttl=int(form["ttl"]),
            priority=int(form["priority"]) if form.get("priority") else None,
            proxied=form.get("proxied", "off") == "on",
            managed_by=form.get("managed_by", "USER")
        )
        repos.DnsRecordRepo(db).create(dns_record)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error creating DNS record: {str(e)}", category="error")

    return RedirectResponse(url="/dns", status_code=303)

@router.get("/dns/edit/{record_id}", response_class=HTMLResponse)
async def get_edit_dns_record(request: Request, record_id: int, db: Session = Depends(get_db)):
    dns_record = repos.DnsRecordRepo(db).get(record_id)
    if not dns_record:
        flash(request, "DNS record not found", category="error")
        return RedirectResponse(url="/dns", status_code=303)

    domains = repos.DomainRepo(db).list_all()
    return templates.TemplateResponse("dns.edit.jinja2", {"request": request, "dns_record": dns_record, "domains": domains})

@router.post("/dns/edit/{record_id}", response_class=RedirectResponse)
async def edit_dns_record(request: Request, record_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        dns_record = repos.DnsRecordRepo(db).get(record_id)
        if not dns_record:
            flash(request, "DNS record not found", category="error")
            return RedirectResponse(url="/dns", status_code=303)

        if dns_record.managed_by != "USER":
            flash(request, "You are not allowed to edit this DNS record", category="error")
            return RedirectResponse(url="/dns", status_code=303)

        dns_record.name = form["name"]
        dns_record.domain_id = form["domain_id"]
        dns_record.type = form["type"]
        dns_record.content = form["content"]
        dns_record.ttl = int(form["ttl"])
        dns_record.priority = int(form["priority"]) if form.get("priority") else None
        dns_record.proxied = form.get("proxied", "off") == "on"

        repos.DnsRecordRepo(db).update(dns_record)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error editing DNS record: {str(e)}", category="error")

    return RedirectResponse(url="/dns", status_code=303)

@router.post("/dns/delete/{record_id}", response_class=RedirectResponse)
async def delete_dns_record(request: Request, record_id: int, db: Session = Depends(get_db)):
    try:
        dns_record = repos.DnsRecordRepo(db).get(record_id)
        if not dns_record:
            flash(request, "DNS record not found", category="error")
            return RedirectResponse(url="/dns", status_code=303)

        repos.DnsRecordRepo(db).delete(dns_record)
    except Exception as e:
        traceback.print_exc()
        flash(request, f"Error deleting DNS record: {str(e)}", category="error")

    return RedirectResponse(url="/dns", status_code=303)