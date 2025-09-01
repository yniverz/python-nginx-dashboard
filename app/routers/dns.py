from fastapi import APIRouter, Depends, Request, Form, Query
from sqlalchemy.orm import Session
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import SessionLocal
from app.repositories import DomainRepo, DnsRecordRepo
from app.models import ManagedBy, DnsType
from app.services.dns import DnsService

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@router.get("/dns")
async def dns_page(request: Request, domain_id:int|None=Query(None), db: Session = Depends(get_db)):
    doms = DomainRepo(db).list()
    selected = domain_id or (doms[0].id if doms else None)
    recs = []
    if selected:
        service = DnsService(db)
        await service.import_provider_records(DomainRepo(db).get(selected))
        recs = DnsRecordRepo(db).list(selected, include=None, active_only=False)
    return templates.TemplateResponse("dns.html", {"request": request, "domains": doms, "selected": selected, "records": recs})

@router.post("/dns/add")
def add_dns_record(
    domain_id:int = Form(...),
    name:str = Form(...),
    type:str = Form(...),
    content:str = Form(...),
    ttl:int|None = Form(None),
    priority:int|None = Form(None),
    proxied:bool|None = Form(None),
    db: Session = Depends(get_db),
):
    repo = DnsRecordRepo(db)
    repo.create_user(domain_id=domain_id, name=name, type=DnsType(type), content=content,
                     ttl=ttl, priority=priority, proxied=proxied, active=True)
    return RedirectResponse(url=f"/dns?domain_id={domain_id}", status_code=303)

@router.post("/dns/{id}/delete")
def delete_dns_record(id:int, domain_id:int = Form(...), db: Session = Depends(get_db)):
    DnsRecordRepo(db).delete_user(id)
    return RedirectResponse(url=f"/dns?domain_id={domain_id}", status_code=303)

@router.post("/dns/{domain_id}/sync")
async def sync_dns(domain_id:int, db: Session = Depends(get_db)):
    from app.services.reconciler import Reconciler
    await Reconciler(db).reconcile(domain_id=domain_id)
    return RedirectResponse(url=f"/dns?domain_id={domain_id}", status_code=303)
