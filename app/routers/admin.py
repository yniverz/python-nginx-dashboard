from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.repositories import DomainRepo, HttpRouteRepo, StreamRouteRepo
from app.services.reconciler import Reconciler
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    doms = DomainRepo(db).list()
    http_count = len(HttpRouteRepo(db).list_all())
    stream_count = len(StreamRouteRepo(db).list_all())
    return templates.TemplateResponse("index.html", {"request": request, "domains": doms, "http_count": http_count, "stream_count": stream_count})

@router.post("/reconcile")
async def reconcile_all(db: Session = Depends(get_db)):
    await Reconciler(db).reconcile()
    return RedirectResponse(url="/", status_code=303)
