"""Storage batch context manager."""

from typing import Optional

from trendradar.storage.results import BatchResult


class StorageBatch:
    """Context handle exposing the final result after normal exit."""

    def __init__(self, backend):
        self.backend = backend
        self.result: Optional[BatchResult] = None

    def __enter__(self):
        self.backend.begin_batch()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            self.result = self.backend.abort_batch()
            return False
        self.result = self.backend.end_batch()
        return False
