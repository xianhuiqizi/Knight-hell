"""Single-process local worker. Persisted steps resume on application restart.

The application and Windows launcher use one server process. A shared lock
serializes manual ticks/cancel/configuration with the worker in that process.
No user session or open browser is needed to advance a running batch.
"""

from __future__ import annotations

import logging
import threading

from flowremote.control_plane.activity import log_event
from flowremote.control_plane.db import utc_now
from flowremote.control_plane.normalization_jobs import tick_normalization

JOB_LOCK = threading.RLock()
logger = logging.getLogger(__name__)


class NormalizationWorker:
    def __init__(self, factory, url, uploads):
        self.factory, self.url, self.uploads = factory, url, uploads
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="normalization-worker", daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=15)

    def run_once(self):
        with self.factory(self.url) as db:
            jobs = db.query("SELECT task_id FROM normalization_batches WHERE status = 'running'")
        for job in jobs:
            if self.stop_event.is_set():
                break
            with JOB_LOCK, self.factory(self.url) as db:
                try:
                    tick_normalization(db, job["task_id"], self.uploads)
                except Exception:
                    logger.exception("Normalization step failed for %s", job["task_id"])
                    now = utc_now()
                    with db.transaction():
                        db.execute(
                            "UPDATE normalization_batches SET status = 'failed', updated_at = ?"
                            " WHERE task_id = ? AND status = 'running'", (now, job["task_id"]),
                        )
                        log_event(db, task_id=job["task_id"], kind="normalize_failed",
                                  actor="Background worker", occurred_at=now,
                                  description="Processing paused after an error. Retry from source files.")

    def run(self):
        while not self.stop_event.wait(0.35):
            try:
                self.run_once()
            except Exception:
                logger.exception("Could not poll normalization queue; retrying")
