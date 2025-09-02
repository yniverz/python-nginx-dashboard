from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

# SQLite file DB; created and managed by this process
engine = create_engine(f"sqlite:///{settings.DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
