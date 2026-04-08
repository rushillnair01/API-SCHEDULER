from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime, timezone


def _utcnow():
    """Return a naive UTC datetime (matches what we store everywhere else)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Target(Base):
    __tablename__ = "targets"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    method = Column(String, nullable=False)
    # default={} on a mutable JSON column is fine; SQLAlchemy copies the value
    # per-row rather than sharing one dict across instances.
    headers = Column(JSON, default=dict)

    # cascade="all, delete-orphan" is stronger than "all, delete":
    # it also removes Schedule rows that are de-associated from a Target
    # (not just when the Target is deleted).
    schedules = relationship(
        "Schedule", back_populates="target", cascade="all, delete-orphan"
    )


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    target_id = Column(Integer, ForeignKey("targets.id", ondelete="CASCADE"), nullable=False)
    interval_seconds = Column(Integer, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    next_run_at = Column(DateTime, nullable=False)
    # Use a callable so each row gets its own timestamp at INSERT time.
    # datetime.datetime.utcnow (no-call) is deprecated in Python 3.12+.
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    target = relationship("Target", back_populates="schedules")
    runs = relationship(
        "Run", back_populates="schedule", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id", ondelete="CASCADE"), nullable=False)
    # PENDING → RUNNING → SUCCESS | FAILURE | INTERRUPTED
    status = Column(String, nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    response_code = Column(Integer, nullable=True)

    schedule = relationship("Schedule", back_populates="runs")