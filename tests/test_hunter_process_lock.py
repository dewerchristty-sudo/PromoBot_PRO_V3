import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import _start_multi_store
from src.promotion_hunter.process_lock import HunterProcessLock
from src.ui.monitor_page import HunterStatusReader, MonitorPage


def _name():
    return rf"Local\PromoBot_Hunter_Test_{uuid4().hex}"


def _child(code, name):
    return subprocess.run(
        [sys.executable, "-c", code, name],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_first_instance_acquires_second_is_refused_and_release_reopens():
    name = _name()
    first = HunterProcessLock(name)
    second = HunterProcessLock(name)
    assert first.acquire()
    assert not second.acquire()
    assert HunterProcessLock.is_locked(name)
    first.release()
    assert second.acquire()
    second.release()


def test_mutex_is_recovered_after_owner_process_crashes():
    name = _name()
    code = (
        "import os,sys; "
        "from src.promotion_hunter.process_lock import HunterProcessLock; "
        "lock=HunterProcessLock(sys.argv[1]); "
        "assert lock.acquire(); os._exit(0)"
    )
    child = _child(code, name)
    assert child.returncode == 0
    recovered = HunterProcessLock(name)
    assert recovered.acquire()
    recovered.release()


def test_concurrent_process_cannot_acquire_held_mutex():
    name = _name()
    owner = HunterProcessLock(name)
    assert owner.acquire()
    code = (
        "import sys; "
        "from src.promotion_hunter.process_lock import HunterProcessLock; "
        "raise SystemExit(0 if not HunterProcessLock(sys.argv[1]).acquire() else 3)"
    )
    child = _child(code, name)
    owner.release()
    assert child.returncode == 0


def test_entrypoint_refuses_second_instance_before_runtime(monkeypatch):
    lock = SimpleNamespace(acquire=lambda: False, release=lambda: None)
    monkeypatch.setattr(
        "src.promotion_hunter.official_runtime.HunterProcessLock", lambda: lock
    )
    assert _start_multi_store.main(["--mode", "analysis_only"]) == 1


def test_interface_does_not_spawn_when_mutex_is_held(monkeypatch):
    page = object.__new__(MonitorPage)
    messages = []
    page.append_activity = messages.append
    monkeypatch.setattr(HunterStatusReader, "_is_process_active", lambda: True)
    page._iniciar_promotion_hunter()
    assert any("ja esta ativo" in message for message in messages)
