"""
Database configuration and session management.
Provides SQLAlchemy engine, session factory, and context managers for database operations.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, scoped_session
from app.config import settings

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass

# Create SQLAlchemy engine with SQLite database
engine = create_engine(f"sqlite:///{settings.db_path()}", echo=False, future=True)

# Create scoped session factory for thread-safe database sessions
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


class DBSession:
    """
    Context manager for database sessions with automatic transaction handling.
    Ensures proper rollback on exceptions and commit on success.
    """
    def __enter__(self):
        self.db = SessionLocal()
        return self.db

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                # Rollback transaction on any exception
                self.db.rollback()
            else:
                # Commit transaction on successful completion
                self.db.commit()
        finally:
            # Always close the session
            self.db.close()

def get_db():
    """
    FastAPI dependency that provides a database session.
    Used with Depends() in route handlers for automatic session management.
    """
    with DBSession() as db:
        yield db