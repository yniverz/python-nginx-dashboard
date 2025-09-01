from fastapi import APIRouter, Depends, Request, Form
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.repositories import DomainRepo, ProviderRepo
from app.schemas import DomainIn
from app.providers.cloudflare import CloudflareDnsClient
from app.services.reconciler import Reconciler
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@router.get("/domains")
def domains_page(request: Request, db: Session = Depends(get_db)):
    doms = DomainRepo(db).list()
    provs = ProviderRepo(db).list()
    return templates.TemplateResponse("domains.html", {"request": request, "domains": doms, "providers": provs})

@router.post("/domains")
async def create_domain(
    name: str = Form(...),
    provider_account_id: int = Form(None),
    provider_zone_id: str = Form(None),
    origin_ipv4: str = Form(None),
    origin_ipv6: str = Form(None),
    auto_wildcard: bool = Form(False),
    auto_direct_prefix: str = Form("direct"),
    acme_email: str = Form(None),
    db: Session = Depends(get_db),
):
    dom = DomainRepo(db).create(
        name=name, provider_account_id=provider_account_id, provider_zone_id=provider_zone_id,
        origin_ipv4=origin_ipv4, origin_ipv6=origin_ipv6,
        auto_wildcard=auto_wildcard, auto_direct_prefix=auto_direct_prefix, acme_email=acme_email
    )
    return RedirectResponse(url="/domains", status_code=303)

@router.post("/domains/{domain_id}/verify-zone")
async def verify_zone(domain_id:int, db: Session = Depends(get_db)):
    dom = DomainRepo(db).get(domain_id)
    if not dom: return RedirectResponse(url="/domains", status_code=303)
    if not dom.provider_account_id:
        return RedirectResponse(url="/domains", status_code=303)
    cf = CloudflareDnsClient()
    zid = await cf.find_zone_id(dom.name)
    if zid:
        DomainRepo(db).update(dom.id, provider_zone_id=zid)
    return RedirectResponse(url="/domains", status_code=303)

@router.post("/domains/{domain_id}/reconcile")
async def reconcile_domain(domain_id:int, db: Session = Depends(get_db)):
    await Reconciler(db).reconcile(domain_id=domain_id)
    return RedirectResponse(url="/", status_code=303)
