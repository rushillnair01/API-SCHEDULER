import requests as http_requests
from datetime import datetime, timezone
from celery import Celery
from .database import SessionLocal
from .models import Run
from .metrics import TOTAL_REQUESTS, HTTP_REQUEST_DURATION

celery_app = Celery("tasks", broker="redis://redis:6379/0")

# Back-end result store lets you inspect task state; optional but useful.
# celery_app.config_from_object({'result_backend': 'redis://redis:6379/1'})


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@celery_app.task(name="execute_request", bind=True, max_retries=3)
def execute_request(self, run_id: int, method: str, url: str, headers: dict):
    db = SessionLocal()
    run = None  # declare before try so the finally block can always reference it

    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            # Run row was deleted between dispatch and execution — nothing to do.
            return f"Run {run_id} not found, skipping"

        run.status = "RUNNING"
        run.started_at = _utcnow()
        db.commit()

        # Measure and record HTTP latency for Prometheus.
        with HTTP_REQUEST_DURATION.time():
            response = http_requests.request(
                method=method,
                url=url,
                headers=headers or {},
                timeout=10,
            )

        run.status = "SUCCESS"
        run.response_code = response.status_code
        run.completed_at = _utcnow()
        TOTAL_REQUESTS.labels(status="SUCCESS").inc()

    except Exception as exc:
        # Retry on transient errors (network blips, timeouts).
        # self.request.retries starts at 0; max_retries=3 means up to 3 retries.
        if self.request.retries < self.max_retries:
            # Exponential back-off: 1s, 2s, 4s
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)

        # Final failure after all retries are exhausted.
        if run is not None:
            run.status = "FAILURE"
            run.completed_at = _utcnow()
        TOTAL_REQUESTS.labels(status="FAILURE").inc()
        print(f"❌ Final failure for Run {run_id}: {exc}")

    finally:
        # Always persist whatever state we reached and release the connection.
        # run may still be None if the initial DB query itself failed.
        if run is not None:
            try:
                db.commit()
            except Exception as commit_err:
                print(f"⚠️ Commit failed for Run {run_id}: {commit_err}")
                db.rollback()
        db.close()