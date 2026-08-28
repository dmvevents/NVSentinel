# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for ServiceChecker (systemd service health via nsenter)."""

import subprocess
from unittest.mock import patch

import pytest

from system_services_monitor.checkers.service_check import ServiceChecker


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    """Build a fake CompletedProcess as returned by subprocess.run."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def checker() -> ServiceChecker:
    return ServiceChecker(flap_window=600, flap_threshold=3)


class TestCheckService:
    def test_active_service_parses_properties(self, checker: ServiceChecker) -> None:
        """systemctl show output is parsed into a populated ServiceStatus."""
        show_output = (
            "ActiveState=active\n"
            "SubState=running\n"
            "MainPID=1234\n"
            "ExecMainStartTimestamp=Wed 2026-01-01 00:00:00 UTC\n"
        )
        nrestarts_output = "NRestarts=0\n"

        # check_service calls _run_host_cmd twice: once for show, once for NRestarts
        with patch.object(
            ServiceChecker,
            "_run_host_cmd",
            side_effect=[_completed(stdout=show_output), _completed(stdout=nrestarts_output)],
        ):
            status = checker.check_service("nvidia-fabricmanager")

        assert status.name == "nvidia-fabricmanager"
        assert status.active is True
        assert status.sub_state == "running"
        assert status.main_pid == 1234
        assert status.n_restarts == 0
        assert status.error is None

    def test_inactive_service_with_failed_returncode(self, checker: ServiceChecker) -> None:
        """A non-zero returncode with no stdout surfaces as error."""
        with patch.object(
            ServiceChecker,
            "_run_host_cmd",
            return_value=_completed(returncode=1, stderr="Unit nvidia-fabricmanager.service could not be found."),
        ):
            status = checker.check_service("nvidia-fabricmanager")

        assert status.active is False
        assert status.error is not None
        assert "could not be found" in status.error

    def test_timeout_returns_error_status(self, checker: ServiceChecker) -> None:
        """subprocess.TimeoutExpired is caught and returns an error ServiceStatus."""
        with patch.object(
            ServiceChecker,
            "_run_host_cmd",
            side_effect=subprocess.TimeoutExpired(cmd=["systemctl"], timeout=10),
        ):
            status = checker.check_service("nvidia-fabricmanager")

        assert status.active is False
        assert status.error == "systemctl show timed out"


class TestFlapDetection:
    def test_flap_detection_triggers_at_threshold(self) -> None:
        """is_flapping flips True once restart count crosses the threshold."""
        c = ServiceChecker(flap_window=600, flap_threshold=3)
        # Seed history (first call only records baseline)
        c._update_flap_tracking("svc", current_restarts=0)
        assert c.is_flapping("svc") is False

        # Each new restart count increment records one timestamp
        c._update_flap_tracking("svc", current_restarts=1)
        c._update_flap_tracking("svc", current_restarts=2)
        assert c.is_flapping("svc") is False  # 2 < threshold(3)

        c._update_flap_tracking("svc", current_restarts=3)
        assert c.is_flapping("svc") is True  # 3 >= threshold(3)

    def test_counter_reset_with_restart_rebaselines_and_keeps_counting(self) -> None:
        """A reset where the process really restarted (start timestamp changed)
        records one observation, so a reboot-causing crash loop is not silenced."""
        c = ServiceChecker(flap_window=600, flap_threshold=3)
        c._update_flap_tracking("svc", current_restarts=5, start_timestamp="t1")  # baseline
        c._update_flap_tracking("svc", current_restarts=6, start_timestamp="t1")  # 1 event

        # Counter resets to 0 across a real restart (e.g. reboot): the changed
        # start timestamp records one event and re-baselines to 0.
        c._update_flap_tracking("svc", current_restarts=0, start_timestamp="t2")
        assert c._last_restart_count["svc"] == 0

        # Counting resumes from the new baseline immediately: one more
        # restart reaches the threshold (1 + 1 reset-event + 1 = 3).
        c._update_flap_tracking("svc", current_restarts=1, start_timestamp="t3")
        assert c.is_flapping("svc") is True

    def test_pure_counter_flush_records_no_restart(self) -> None:
        """`systemctl reset-failed` on a running service flushes NRestarts without
        restarting the process — no phantom restart may be recorded."""
        c = ServiceChecker(flap_window=600, flap_threshold=3)
        c._update_flap_tracking("svc", current_restarts=5, start_timestamp="t1")  # baseline
        c._update_flap_tracking("svc", current_restarts=7, start_timestamp="t1")  # 2 events

        # Admin runs reset-failed: counter drops to 0, start timestamp unchanged.
        c._update_flap_tracking("svc", current_restarts=0, start_timestamp="t1")
        assert c._last_restart_count["svc"] == 0
        assert len(c._restart_history["svc"]) == 2  # no phantom third event

        # A reset without any timestamp evidence is also conservative: nothing recorded.
        c._update_flap_tracking("svc", current_restarts=3, start_timestamp="t1")  # 3 events -> flapping
        assert c.is_flapping("svc") is True

    def test_unobserved_probe_leaves_baseline_untouched(self) -> None:
        """None (probe failed / NRestarts unsupported) must not move the baseline."""
        c = ServiceChecker(flap_window=600, flap_threshold=3)
        c._update_flap_tracking("svc", current_restarts=4)  # baseline
        c._update_flap_tracking("svc", current_restarts=None)  # no observation
        assert c._last_restart_count["svc"] == 4
        assert c.is_flapping("svc") is False

        # A later real observation still diffs against the old baseline.
        c._update_flap_tracking("svc", current_restarts=7)  # 3 events
        assert c.is_flapping("svc") is True
