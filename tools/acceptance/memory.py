"""Read-only Windows working-set sampling for local acceptance, not a task memory budget."""

import ctypes
import os
import threading
import time
from ctypes import wintypes


class WindowsWorkingSet:
    """Hold one process handle so a reused PID cannot silently change the observation."""

    def __init__(self, pid):
        if os.name != "nt":
            raise NotImplementedError("Windows working-set backend unavailable")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.GetExitCodeProcess.restype = wintypes.BOOL
        self.kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.kernel.GetProcessTimes.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            created, ended, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in (created, ended, kernel_time, user_time))):
                raise ctypes.WinError(ctypes.get_last_error())
            self.identity = str((created.dwHighDateTime << 32) | created.dwLowDateTime)

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t)
                    for name in (
                        "PeakWorkingSetSize",
                        "WorkingSetSize",
                        "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage",
                        "PagefileUsage",
                        "PeakPagefileUsage",
                    )
                ]

            self.counters_type = Counters
            self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        except Exception:
            self.close()
            raise

    def read(self):
        exit_code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            raise ProcessLookupError("Selected process has stopped")
        counters = self.counters_type()
        counters.cb = ctypes.sizeof(counters)
        if not self.psapi.GetProcessMemoryInfo(self.handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(counters.WorkingSetSize)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class MemoryObservation:
    """Finite sampling interval; missing or partial observations never become measured peaks."""

    def __init__(self, pid=None, *, interval=0.02, reader_factory=WindowsWorkingSet):
        if pid is not None and (type(pid) is not int or not 0 < pid < 2**32):
            raise ValueError("A positive process PID is required")
        if not 0.001 <= interval <= 1:
            raise ValueError("Sampling interval must be between 1 ms and 1 s")
        self.pid, self.interval, self.reader_factory = pid, interval, reader_factory
        self.samples, self.errors = [], []
        self.reader = self.thread = None
        self.stop = threading.Event()

    def sample(self):
        try:
            self.samples.append((time.monotonic() - self.started, self.reader.read()))
        except (OSError, NotImplementedError) as error:
            self.errors.append(type(error).__name__)
            self.stop.set()

    def collect(self):
        while not self.stop.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.started = time.monotonic()
        if self.pid is not None:
            try:
                self.reader = self.reader_factory(self.pid)
                self.sample()
                if not self.errors:
                    self.thread = threading.Thread(target=self.collect, daemon=True)
                    self.thread.start()
            except (OSError, NotImplementedError) as error:
                self.errors.append(type(error).__name__)
        return self

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join()
        if self.reader:
            try:
                if not self.errors:
                    self.sample()
            finally:
                self.reader.close()
        values = [value for _, value in self.samples]
        self.evidence = {
            "basis": "Windows-GetProcessMemoryInfo-WorkingSetSize-sampled",
            "pid": self.pid,
            "process_creation_filetime": getattr(self.reader, "identity", None),
            "scope": "selected process; submission through download; excludes children, Office, browser and QA client",
            "task_exclusive": None,
            "interval_seconds": self.interval,
            "samples": len(values),
            "max_observed_gap_seconds": max((b[0] - a[0] for a, b in zip(self.samples, self.samples[1:])), default=None),
            "duration_seconds": time.monotonic() - self.started,
            "complete_observation": bool(values) and not self.errors,
            "baseline_rss_bytes": values[0] if values else None,
            "max_sampled_rss_bytes": max(values) if values else None,
            "true_interval_peak_bytes": None,
            "errors": self.errors,
            "unavailable_reason": "not-requested" if self.pid is None else "sampling-failed" if self.errors else None,
        }
        return False
