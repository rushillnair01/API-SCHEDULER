from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import asc
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response
from typing import List, Optional
from datetime import datetime, timezone
from . import models, database, schemas

app = FastAPI(title="CONSUMA - API CRON JOB TOOL")


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------

@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    """Expose Prometheus metrics in text format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/metrics/stats")
def get_aggregate_stats(db: Session = Depends(database.get_db)):
    total_runs = db.query(models.Run).count()
    successes = db.query(models.Run).filter(models.Run.status == "SUCCESS").count()
    return {
        "total_runs": total_runs,
        "success_rate": f"{(successes / total_runs) * 100:.1f}%" if total_runs > 0 else "0%",
        "active_schedules": db.query(models.Schedule).filter(models.Schedule.is_active == True).count(),
        "total_targets": db.query(models.Target).count(),
    }


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

@app.post("/targets/", response_model=schemas.Target, status_code=201)
def create_target(target: schemas.TargetCreate, db: Session = Depends(database.get_db)):
    db_target = models.Target(**target.model_dump())
    db.add(db_target)
    db.commit()
    db.refresh(db_target)
    return db_target


@app.get("/targets/", response_model=List[schemas.Target])
def list_targets(db: Session = Depends(database.get_db)):
    return db.query(models.Target).all()


@app.delete("/targets/{target_id}")
def delete_target(target_id: int, db: Session = Depends(database.get_db)):
    # Fetch first so SQLAlchemy's Python-level cascade fires correctly.
    # A raw .delete() bulk operation bypasses relationship cascade handlers.
    target = db.query(models.Target).filter(models.Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    db.delete(target)
    db.commit()
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

@app.post("/schedules/", response_model=schemas.Schedule, status_code=201)
def create_schedule(sched: schemas.ScheduleCreate, db: Session = Depends(database.get_db)):
    # Verify the target exists before creating a schedule for it.
    target = db.query(models.Target).filter(models.Target.id == sched.target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    db_sched = models.Schedule(
        target_id=sched.target_id,
        interval_seconds=sched.interval_seconds,
        duration_seconds=sched.duration_seconds,
        next_run_at=now_utc,
        created_at=now_utc,
        is_active=True,
    )
    db.add(db_sched)
    db.commit()
    db.refresh(db_sched)
    return db_sched


@app.get("/schedules/", response_model=List[schemas.Schedule])
def list_schedules(db: Session = Depends(database.get_db)):
    return db.query(models.Schedule).all()


@app.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(database.get_db)):
    # Fetch first — same reason as delete_target above.
    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    db.delete(schedule)
    db.commit()
    return {"status": "deleted"}


@app.post("/schedules/{schedule_id}/pause")
def pause_schedule(schedule_id: int, db: Session = Depends(database.get_db)):
    sched = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if not sched.is_active:
        return {"status": "already_paused"}
    sched.is_active = False
    db.commit()
    return {"status": "paused"}


@app.post("/schedules/{schedule_id}/resume")
def resume_schedule(schedule_id: int, db: Session = Depends(database.get_db)):
    sched = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if sched.is_active:
        return {"status": "already_active"}
    sched.is_active = True
    # Reset next_run_at so the scheduler picks it up immediately.
    sched.next_run_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"status": "resumed"}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@app.get("/runs/", response_model=List[schemas.Run])
def list_runs(
    schedule_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(database.get_db),
):
    query = db.query(models.Run)
    if schedule_id:
        query = query.filter(models.Run.schedule_id == schedule_id)
    if status:
        # Validate status value so bad filter params return a clear error.
        valid_statuses = {"PENDING", "RUNNING", "SUCCESS", "FAILURE", "INTERRUPTED"}
        if status.upper() not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Must be one of {sorted(valid_statuses)}",
            )
        query = query.filter(models.Run.status == status.upper())
    return query.order_by(asc(models.Run.id)).all()