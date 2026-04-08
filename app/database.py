from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/scheduler_db")

# pool_pre_ping=True: drops and recreates connections that went stale (e.g. after
# a DB restart or a long idle period). Without this, stale connections raise
# cryptic OperationalErrors at query time.
# pool_size / max_overflow: explicit caps so the scheduler loop (which opens a
# new session every second) cannot exhaust PostgreSQL's connection limit.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# declarative_base() was moved from sqlalchemy.ext.declarative to
# sqlalchemy.orm in SQLAlchemy 1.4 and the ext path is deprecated in 2.x.
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and guarantees cleanup."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()   # roll back any partial transaction on unhandled errors
        raise
    finally:
        db.close()