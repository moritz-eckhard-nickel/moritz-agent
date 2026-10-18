# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import json
import os
import time

from moritz_agent.phone.control import PhoneControl, read_status, run_dir


def test_status_is_written_atomically_and_readable(tmp_path):
    control = PhoneControl(tmp_path, "9.9.9")
    control.write_status({"registration": "registered", "in_call": True, "calls_total": 3})
    status = read_status(tmp_path)
    assert status is not None
    assert status["registration"] == "registered" and status["in_call"] is True
    assert status["version"] == "9.9.9" and status["pid"] == os.getpid()
    assert not list(run_dir(tmp_path).glob("*.tmp"))  # no leftover temp file


def test_stale_stopped_and_broken_status_mean_no_live_service(tmp_path):
    assert read_status(tmp_path) is None  # nothing written yet
    control = PhoneControl(tmp_path, "1")
    control.write_status({"registration": "registered"})
    assert read_status(tmp_path) is not None
    control.write_stopped()
    assert read_status(tmp_path) is None
    control.write_status({"registration": "registered"})
    path = control.status_path
    data = json.loads(path.read_text())
    data["updated"] = time.time() - 60
    path.write_text(json.dumps(data))
    assert read_status(tmp_path) is None  # older than a few seconds: the service is gone
    path.write_text("{not json")
    assert read_status(tmp_path) is None


def test_drain_flag_follows_the_file(tmp_path):
    control = PhoneControl(tmp_path, "1")
    assert not control.draining()
    control.directory.mkdir(parents=True)
    control.drain_path.write_text("")
    assert control.draining()
    control.write_status({"in_call": False})
    assert read_status(tmp_path)["draining"] is True
    control.drain_path.unlink()
    assert not control.draining()


def test_unwritable_data_dir_does_not_raise(tmp_path):
    blocker = tmp_path / "data"
    blocker.write_text("a file where the directory should be")
    PhoneControl(tmp_path, "1").write_status({"in_call": False})  # must not raise
