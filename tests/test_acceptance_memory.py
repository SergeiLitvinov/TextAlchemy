"""Independent process observation: finite samples are not true task peaks."""

import os
import time

import pytest

from tools.acceptance.memory import MemoryObservation


def test_unspecified_process_stays_unknown():
    with MemoryObservation() as observed:
        pass
    assert observed.evidence["samples"] == 0
    assert observed.evidence["baseline_rss_bytes"] is None
    assert observed.evidence["max_sampled_rss_bytes"] is None
    assert observed.evidence["unavailable_reason"] == "not-requested"


def test_failed_observation_does_not_replace_an_operation_error_or_invent_memory():
    def unavailable(pid):
        raise PermissionError("Own test access denied")
    observed = MemoryObservation(123, reader_factory=unavailable)
    with pytest.raises(RuntimeError, match="Own operation failed"), observed:
        raise RuntimeError("Own operation failed")
    assert observed.evidence["max_sampled_rss_bytes"] is None
    assert not observed.evidence["complete_observation"]
    assert observed.evidence["errors"] == ["PermissionError"]


def test_terminated_process_keeps_partial_samples_explicitly_incomplete():
    class Reader:
        identity = "own-process-lifetime"
        closed = False
        reads = 0
        def read(self):
            self.reads += 1
            if self.reads > 1:
                raise ProcessLookupError("Own process stopped")
            return 2048
        def close(self):
            self.closed = True
    reader = Reader()
    with MemoryObservation(123, reader_factory=lambda pid: reader) as observed:
        pass
    assert reader.closed
    assert observed.evidence["samples"] == 1
    assert not observed.evidence["complete_observation"]
    assert observed.evidence["true_interval_peak_bytes"] is None
    assert observed.evidence["process_creation_filetime"] == reader.identity


@pytest.mark.skipif(os.name != "nt", reason="Real Windows working-set backend")
def test_real_current_process_allocation_is_measured_and_handle_is_closed():
    with MemoryObservation(os.getpid()) as observed:
        held = bytearray(b"x" * (32 * 1024 * 1024))
        time.sleep(0.08)
    record = observed.evidence
    assert held[0] == ord("x")
    assert record["complete_observation"] and record["samples"] >= 3
    assert record["max_sampled_rss_bytes"] >= record["baseline_rss_bytes"] + 16 * 1024 * 1024
    assert record["true_interval_peak_bytes"] is None and record["task_exclusive"] is None
    assert record["process_creation_filetime"]
    assert observed.reader.handle is None
