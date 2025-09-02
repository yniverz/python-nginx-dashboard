from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, scoped_session
from app.config import settings

class Base(DeclarativeBase):
    pass

engine = create_engine(f"sqlite:///{settings.db_path()}", echo=False, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
