"""Storage-layer exception hierarchy."""


class StorageError(Exception):
    """Base class for storage failures."""


class StorageWriteError(StorageError):
    """Raised when an atomic storage write cannot be committed."""


class RemoteStorageError(StorageError):
    """Base class for remote object storage failures."""


class RemoteDependencyError(RemoteStorageError):
    """The remote provider could not answer the requested operation."""


class RemoteDataError(RemoteStorageError):
    """Downloaded remote data failed integrity validation."""


class RemoteConflictError(RemoteStorageError):
    """A conditional object write lost an optimistic concurrency race."""


class RemoteConditionalWriteUnsupported(RemoteStorageError):
    """The provider rejected the required conditional write semantics."""
