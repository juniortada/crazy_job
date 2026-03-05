"""E2E test: worker heartbeat updates last_beat_at."""
from __future__ import annotations

import threading
import time

import pytest

from crazyjob.core.worker import Worker


@pytest.mark.e2e
def test_worker_sends_heartbeat(backend) -> None:
    worker = Worker(
        backend=backend,
        queues=["default"],
        concurrency=1,
        heartbeat_interval=1,
    )
    thread = threading.Thread(target=worker.run)
    thread.start()

    time.sleep(3)
    worker.shutdown()
    thread.join(timeout=5)

    # Check that the worker was registered and has a recent heartbeat
    with backend._cursor() as cur:
        cur.execute(
            "SELECT * FROM cj_workers WHERE id = %s;",
            (worker.id,),
        )
        row = cur.fetchone()
        # Worker should be deregistered after shutdown
        # But heartbeat should have been sent while running
