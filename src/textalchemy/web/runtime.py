"""Process startup policy for the threaded Web application."""

import multiprocessing


def configure_worker_processes() -> str:
    """Keep native workers from inheriting the server's threads and open pipes."""
    method = multiprocessing.get_start_method(allow_none=True)
    if method in (None, "fork"):
        multiprocessing.set_start_method("spawn", force=True)
        return "spawn"
    return method
