"""A process-owned exclusive lock on a persistent coordination file."""

from contextlib import contextmanager
import os

from .paths import is_link

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = [("internal", ctypes.c_size_t), ("internal_high", ctypes.c_size_t),
                    ("offset", wintypes.DWORD), ("offset_high", wintypes.DWORD),
                    ("event", wintypes.HANDLE)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    acquire = kernel.LockFileEx
    acquire.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                        wintypes.DWORD, ctypes.POINTER(Overlapped)]
    acquire.restype = wintypes.BOOL
else:
    import fcntl


@contextmanager
def file_lock(path, *, blocking=True):
    if is_link(path):
        raise ValueError("lock path is a link or reparse point")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "rb+") as stream:
        if os.name == "nt":
            handle = msvcrt.get_osfhandle(stream.fileno())
            state = Overlapped()
            if not acquire(handle, 2 | (0 if blocking else 1), 0, 1, 0, ctypes.byref(state)):
                code = ctypes.get_last_error()
                if code != 33 or blocking:  # ERROR_LOCK_VIOLATION
                    raise ctypes.WinError(code)
                yield False
                return
        else:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                if blocking:
                    raise
                yield False
                return
        yield True
        # A close releases the lock even if the caller raises or the process dies.
