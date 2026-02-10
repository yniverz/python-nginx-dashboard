"""
Database configuration and session management.
Provides SQLAlchemy engine, session factory, and context managers for database operations.
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, scoped_session
from app.config import settings

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass

# Create SQLAlchemy engine with SQLite database
engine = create_engine(f"sqlite:///{settings.db_path()}", echo=False, future=True)

# Create scoped session factory for thread-safe database sessions
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


def _migrate_dns_records_constraint(conn, inspector) -> None:
    """
    Migrate dns_records table to include proxied field in unique constraint.
    This handles backward compatibility with databases created before this change.
    """
    if "dns_records" not in inspector.get_table_names():
        return
    
    # Check if migration is needed by examining the unique constraints
    constraints = inspector.get_unique_constraints("dns_records")
    for constraint in constraints:
        if constraint.get("name") == "uq_dns_key":
            # Check if the constraint already includes 'proxied'
            cols = constraint.get("column_names", [])
            if "proxied" in cols:
                # Already migrated
                return
            
            # Need to migrate: recreate table with new constraint
            # SQLite doesn't support dropping constraints, so we recreate the table
            conn.execute(text("""
                CREATE TABLE dns_records_new (
                    id INTEGER PRIMARY KEY,
                    domain_id INTEGER NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    type VARCHAR(10) NOT NULL,
                    content VARCHAR(1024) NOT NULL,
                    ttl INTEGER DEFAULT 1,
                    priority INTEGER,
                    proxied BOOLEAN,
                    managed_by VARCHAR(10) NOT NULL DEFAULT 'USER',
                    meta JSON DEFAULT '{}',
                    FOREIGN KEY (domain_id) REFERENCES domains(id),
                    CONSTRAINT uq_dns_key UNIQUE (domain_id, name, type, content, proxied)
                )
            """))
            
            # Copy data from old table to new table
            conn.execute(text("""
                INSERT INTO dns_records_new 
                (id, domain_id, name, type, content, ttl, priority, proxied, managed_by, meta)
                SELECT id, domain_id, name, type, content, ttl, priority, proxied, managed_by, meta
                FROM dns_records
            """))
            
            # Drop old table
            conn.execute(text("DROP TABLE dns_records"))
            
            # Rename new table to original name
            conn.execute(text("ALTER TABLE dns_records_new RENAME TO dns_records"))
            
            return


def ensure_schema() -> None:
    """
    Ensure database schema exists and apply lightweight migrations for new columns.
    """
    Base.metadata.create_all(bind=engine)

    return

    with engine.begin() as conn:
        inspector = inspect(conn)
        if "domains" not in inspector.get_table_names():
            return

        # Migration: Add dns_proxy_enabled column to domains table if missing
        domain_columns = {col["name"] for col in inspector.get_columns("domains")}
        if "dns_proxy_enabled" not in domain_columns:
            conn.execute(text("ALTER TABLE domains ADD COLUMN dns_proxy_enabled BOOLEAN NOT NULL DEFAULT 1"))
        
        # Migration: Update dns_records unique constraint to include proxied field
        _migrate_dns_records_constraint(conn, inspector)


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