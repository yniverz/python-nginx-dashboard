from fastapi import APIRouter, Depends, Request, Form
from sqlalchemy.orm import Session
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import SessionLocal
from app.repositories import DomainRepo, HttpRouteRepo

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@router.get("/http")
def http_page(request: Request, db: Session = Depends(get_db)):
    doms = DomainRepo(db).list()
    routes = []
    for d in doms:
        for r in HttpRouteRepo(db).list_by_domain(d.id):
            routes.append((d, r))
    return templates.TemplateResponse("http_routes.html", {"request": request, "domains": doms, "routes": routes})

@router.post("/http")
def create_http_route(
    domain_id:int = Form(...),
    subdomain:str = Form(...),
    backend_url:str = Form(...),
    db: Session = Depends(get_db),
):
    HttpRouteRepo(db).create(domain_id=domain_id, subdomain=subdomain, backend_url=backend_url)
    return RedirectResponse(url="/http", status_code=303)

@router.post("/http/{route_id}/delete")
def delete_http_route(route_id:int, db: Session = Depends(get_db)):
    HttpRouteRepo(db).delete(route_id)
    return RedirectResponse(url="/http", status_code=303)
