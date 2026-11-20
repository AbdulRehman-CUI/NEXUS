import threading
import time

import pytest
from conftest import ready, upload
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from nexus.config import Settings
from nexus.database import Job
from nexus.main import create_app


def test_worker_recovers_from_failed_queue_select(client, workspace):
    service = client.app.state.service
    worker = service.thread
    failed = threading.Event()

    def fail_once(conn, cursor, statement, parameters, context, many):
        if threading.current_thread() is worker and "FROM jobs" in statement and not failed.is_set():
            failed.set()
            raise OperationalError(None, None, OSError("temporary queue failure"))

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", fail_once)
    try:
        item = upload(client, workspace)
        assert failed.wait(3)
        worker.join(0.05)
        assert worker.is_alive()
        assert ready(client, workspace, item["document"]["id"])["chunk_count"] > 0
        assert service.thread is worker
        with service.sessions() as session:
            jobs = session.scalars(select(Job).where(Job.document_id == item["document"]["id"])).all()
            assert [(job.id, job.status, job.attempts) for job in jobs] == [(item["job_id"], "ready", 1)]
    finally:
        event.remove(engine, "before_cursor_execute", fail_once)


def test_repeated_queue_failures_back_off_and_shutdown_wakes_worker(client, monkeypatch):
    service = client.app.state.service
    delays = []
    at_cap = threading.Event()
    wait = service.stop_event.wait

    def unavailable():
        raise OperationalError(None, None, OSError("temporary queue failure"))

    def observe_delay(delay):
        delays.append(delay)
        if len(delays) == 10:
            at_cap.set()
            return wait(delay)
        return False

    monkeypatch.setattr(service, "process_one", unavailable)
    monkeypatch.setattr(service.stop_event, "wait", observe_delay)
    service.wake.set()
    assert at_cap.wait(3)
    assert 0 < delays[0] < delays[-1] <= 30
    assert delays == sorted(delays) and delays[-1] == delays[-2]
    assert client.get("/health").status_code == 503
    start = time.monotonic()
    service.close()
    assert not service.thread.is_alive() and time.monotonic() - start < 1


@pytest.mark.parametrize("profile", ["local", "server"])
@pytest.mark.parametrize("required", [False, True])
def test_health_accounts_for_required_worker(tmp_path, monkeypatch, profile, required):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash",
                        profile=profile, worker_enabled=required)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["status"] == "ok"
        if required:
            observed = []
            service = client.app.state.service

            def fatal():
                raise RuntimeError("unexpected worker failure")

            monkeypatch.setattr(threading, "excepthook", lambda failure: observed.append(failure.exc_type))
            monkeypatch.setattr(service, "process_one", fatal)
            service.wake.set()
            service.thread.join(3)
            assert observed == [RuntimeError] and not service.thread.is_alive()
        health = client.get("/health")
        assert health.status_code == (503 if required else 200)
        assert (health.json()["status"] == "ok") is (not required)
        if profile == "server":
            assert set(health.json()) == {"status"}
