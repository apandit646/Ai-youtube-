"""Background worker: polls the DB job queue and runs periodic schedules (APScheduler).

Run with:  python -m app.workers.main
"""

import logging
import os
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models import AppSettings, ConnectedYouTubeChannel
from app.models.enums import JobKind
from app.services import jobs
from app.workers.handlers import run_job

log = logging.getLogger("worker")

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def heartbeat_path():
    """Stored on the shared media volume so the API container can report worker liveness."""
    return get_settings().media_root / ".worker-heartbeat"


def schedule_automation() -> None:
    """Daily automation: one pipeline run per owner per configured day, only when explicitly enabled."""
    with SessionLocal() as db:
        for s in db.scalars(select(AppSettings).where(AppSettings.automation_enabled.is_(True),
                                                      AppSettings.paused.is_(False))):
            today = datetime.now(UTC).date().isoformat()
            if datetime.now(UTC).weekday() not in (s.publish_days or range(7)):
                continue
            jobs.enqueue(db, s.owner_id, JobKind.PIPELINE, {"trigger": "schedule"},
                         dedupe_key=f"pipeline:{s.owner_id}:{today}")
        db.commit()


def schedule_analytics() -> None:
    with SessionLocal() as db:
        owners = set(db.scalars(select(ConnectedYouTubeChannel.owner_id).where(
            ConnectedYouTubeChannel.is_active.is_(True))))
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H")
        for owner in owners:
            jobs.enqueue(db, owner, JobKind.ANALYTICS, {"days": 28}, dedupe_key=f"analytics:{owner}:{stamp}")
        db.commit()


def recover() -> None:
    with SessionLocal() as db:
        n = jobs.recover_stale(db)
        db.commit()
    if n:
        log.warning("re-queued %d stale jobs", n)


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.stop = threading.Event()
        self.slots = threading.Semaphore(self.settings.max_concurrent_jobs)
        self.pool = ThreadPoolExecutor(max_workers=self.settings.max_concurrent_jobs)

    def _run(self, job_id: int) -> None:
        try:
            with SessionLocal() as db:
                job = db.get(jobs.Job, job_id)
                run_job(db, job)
        except Exception:  # noqa: BLE001
            log.exception("worker crashed while running job", extra={"job_id": job_id})
        finally:
            self.slots.release()

    def loop(self) -> None:
        while not self.stop.is_set():
            try:
                heartbeat_path().write_text(datetime.now(UTC).isoformat())
            except OSError:
                log.warning("cannot write worker heartbeat")
            if not self.slots.acquire(timeout=self.settings.worker_poll_interval_seconds):
                continue
            try:
                with SessionLocal() as db:
                    job = jobs.claim_next(db, WORKER_ID)
                    job_id = job.id if job else None
            except Exception:  # noqa: BLE001 - DB hiccup; back off
                log.exception("failed to poll job queue")
                job_id = None
                time.sleep(5)
            if job_id is None:
                self.slots.release()
                self.stop.wait(self.settings.worker_poll_interval_seconds)
                continue
            self.pool.submit(self._run, job_id)
        self.pool.shutdown(wait=True)


def wait_for_db(timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while True:
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
            return
        except Exception:  # noqa: BLE001
            if time.time() > deadline:
                raise
            time.sleep(2)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    wait_for_db()
    recover()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(recover, "interval", minutes=5, id="recover")
    scheduler.add_job(schedule_analytics, "interval", hours=6, id="analytics", next_run_time=datetime.now(UTC))
    scheduler.add_job(schedule_automation, "cron", hour=3, minute=17, id="automation")
    scheduler.start()
    worker = Worker()

    def _stop(*_: object) -> None:
        log.info("shutting down worker")
        worker.stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started", extra={"step": WORKER_ID})
    worker.loop()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
