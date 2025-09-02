from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, scoped_session
from app.config import settings

class Base(DeclarativeBase):
    pass

engine = create_engine(f"sqlite:///{settings.db_path()}", echo=False, future=True)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


class DBSession:
    """Context manager for a single SQLAlchemy Session."""
    def __enter__(self):
        self.db = SessionLocal()
        return self.db

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self.db.rollback()
            else:
                self.db.commit()
        finally:
            self.db.close()

def get_db():
    with DBSession() as db:
        yield db