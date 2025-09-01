from fastapi import APIRouter, Depends, Request, Form
from sqlalchemy.orm import Session
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import SessionLocal
from app.repositories import DomainRepo, StreamRouteRepo

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@router.get("/stream")
def stream_page(request: Request, db: Session = Depends(get_db)):
    doms = DomainRepo(db).list()
    routes = []
    for d in doms:
        for r in StreamRouteRepo(db).list_by_domain(d.id):
            routes.append((d, r))
    return templates.TemplateResponse("stream_routes.html", {"request": request, "domains": doms, "routes": routes})

@router.post("/stream")
def create_stream_route(
    domain_id:int = Form(...),
    subdomain:str = Form(...),
    port:int = Form(...),
    target:str = Form(...),
    srv_record:str|None = Form(None),
    active:bool = Form(True),
    db: Session = Depends(get_db),
):
    StreamRouteRepo(db).create(domain_id=domain_id, subdomain=subdomain, port=port, target=target, srv_record=srv_record, active=active)
    return RedirectResponse(url="/stream", status_code=303)

@router.post("/stream/{route_id}/delete")
def delete_stream_route(route_id:int, db: Session = Depends(get_db)):
    StreamRouteRepo(db).delete(route_id)
    return RedirectResponse(url="/stream", status_code=303)
