import time
import datetime
from app.database import SessionLocal
from app.models import Schedule, Run
from app.tasks import execute_request


def _utcnow() -> datetime.datetime:
    """Naive UTC datetime — matches what's stored in every DateTime column."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def handle_crash_recovery() -> None:
    """
    Called once at startup to clean up state left by an ungraceful shutdown.

    Order matters:
      1. Mark all RUNNING rows as INTERRUPTED first.  These tasks were
         mid-flight when the process died; they will never finish on their own.
      2. Re-dispatch PENDING rows whose schedule is still active.  These were
         enqueued to Redis but the worker never picked them up (Redis may have
         restarted too), so we push the Celery task again.
      3. Retry INTERRUPTED rows as fresh PENDING runs so interrupted work is
         re-attempted.  The original INTERRUPTED row is kept as an audit record.
    """
    db = SessionLocal()
    try:
        # --- Step 1: RUNNING → INTERRUPTED ---
        running_runs = db.query(Run).filter(Run.status == "RUNNING").all()
        now = _utcnow()
        for run in running_runs:
            run.status = "INTERRUPTED"
            run.completed_at = now
        if running_runs:
            db.commit()
            print(f"🔴 Marked {len(running_runs)} RUNNING run(s) as INTERRUPTED")

        # --- Step 2: Re-dispatch PENDING ---
        pending_runs = db.query(Run).filter(Run.status == "PENDING").all()
        redispatched = 0
        for run in pending_runs:
            job = run.schedule
            # Only re-dispatch if the schedule still exists, is still active,
            # and the target still exists.  A paused or deleted schedule means
            # the operator intentionally stopped it — don't restart it.
            if job and job.is_active and job.target:
                execute_request.delay(
                    run.id, job.target.method, job.target.url, job.target.headers
                )
                redispatched += 1
                time.sleep(0.05)   # small throttle to avoid Redis burst
            else:
                # Schedule is gone or paused — mark the orphaned run as FAILURE
                # so it doesn't stay PENDING forever.
                run.status = "FAILURE"
                run.completed_at = _utcnow()

        if pending_runs:
            db.commit()
            print(
                f"🟡 Processed {len(pending_runs)} PENDING run(s): "
                f"{redispatched} re-dispatched, "
                f"{len(pending_runs) - redispatched} marked FAILURE (inactive/deleted schedule)"
            )

        # --- Step 3: Re-execute INTERRUPTED runs (fresh attempt) ---
        interrupted_runs = db.query(Run).filter(Run.status == "INTERRUPTED").all()
        retried = 0
        for run in interrupted_runs:
            job = run.schedule
            if job and job.is_active and job.target:
                # Create a brand new Run row — don't mutate the INTERRUPTED one.
                # The INTERRUPTED row stays as an honest record of the crash.
                new_run = Run(
                    schedule_id=job.id,
                    status="PENDING",
                    scheduled_at=_utcnow(),
                )
                db.add(new_run)
                db.flush()  # get the new ID before dispatch
                execute_request.delay(
                    new_run.id, job.target.method, job.target.url, job.target.headers
                )
                retried += 1
                time.sleep(0.05)

        if interrupted_runs:
            db.commit()
            print(f"🔁 Retried {retried} INTERRUPTED run(s) as fresh PENDING runs")

    except Exception as exc:
        print(f"⚠️ Recovery error: {exc}")
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> None:
    """
    Main scheduler loop.  Runs forever, polling for due schedules every second.

    For each active schedule whose next_run_at is in the past:
      - If its duration window has expired, deactivate it and skip.
      - Otherwise create a PENDING Run, advance next_run_at, and hand off to Celery.
    """
    print("🚀 Scheduler starting — running crash recovery...")
    handle_crash_recovery()
    print("✅ Crash recovery complete — entering main loop")

    while True:
        db = SessionLocal()
        now = _utcnow()

        try:
            due_jobs = (
                db.query(Schedule)
                .filter(Schedule.next_run_at <= now, Schedule.is_active == True)
                .all()
            )

            for job in due_jobs:
                # --- Kill-switch: deactivate expired duration window ---
                if job.duration_seconds:
                    expiry_time = job.created_at + datetime.timedelta(
                        seconds=job.duration_seconds
                    )
                    if now >= expiry_time:
                        print(f"🛑 Window expired for Schedule {job.id} — deactivating")
                        job.is_active = False
                        db.commit()
                        continue

                # --- Guard: skip if target was deleted without cascade cleanup ---
                if not job.target:
                    print(f"⚠️ Schedule {job.id} has no target — deactivating")
                    job.is_active = False
                    db.commit()
                    continue

                # 1. Create the Run record in PENDING state.
                new_run = Run(
                    schedule_id=job.id,
                    status="PENDING",
                    scheduled_at=job.next_run_at,
                )
                db.add(new_run)

                # 2. Advance next_run_at before committing so that if the
                #    commit succeeds but Celery dispatch fails, the scheduler
                #    won't re-dispatch on the very next tick.
                job.next_run_at = job.next_run_at + datetime.timedelta(
                    seconds=job.interval_seconds
                )
                db.commit()
                db.refresh(new_run)

                # 3. Hand off to Celery worker.
                execute_request.delay(
                    new_run.id, job.target.method, job.target.url, job.target.headers
                )
                print(f"✅ Dispatched: Schedule {job.id} → Run {new_run.id}")

                # Small throttle to avoid Redis burst and 429s on targets.
                time.sleep(0.1)

        except Exception as exc:
            print(f"⚠️ Scheduler loop error: {exc}")
            db.rollback()
        finally:
            db.close()

        time.sleep(1)


if __name__ == "__main__":
    start_scheduler()