"""Windows process tree limits and a startup gate for job assignment."""

import ctypes
from ctypes import wintypes
import msvcrt
import os
import subprocess
import sys


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


kernel = ctypes.WinDLL("kernel32", use_last_error=True)


def bind(name, result, *args):
    api = getattr(kernel, name)
    api.restype = result
    api.argtypes = args
    return api


create_job = bind("CreateJobObjectW", wintypes.HANDLE, ctypes.c_void_p, wintypes.LPCWSTR)
set_job = bind("SetInformationJobObject", wintypes.BOOL, wintypes.HANDLE, ctypes.c_int,
               ctypes.c_void_p, wintypes.DWORD)
assign = bind("AssignProcessToJobObject", wintypes.BOOL, wintypes.HANDLE, wintypes.HANDLE)
open_process = bind("OpenProcess", wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
close = bind("CloseHandle", wintypes.BOOL, wintypes.HANDLE)

# This child has one inherited gate read handle. The caller alone owns its write
# end. An exit before assignment closes the gate and leaves no workload running.
GATE = """
import ctypes, msvcrt, os, subprocess, sys
ctypes.windll.kernel32.SetErrorMode(0x8003)  # Keep loader failures in the child exit code.
with os.fdopen(msvcrt.open_osfhandle(int(sys.argv[1]), os.O_RDONLY | os.O_BINARY), "rb") as gate:
    if gate.read(1) != b"1":
        sys.exit(125)
sys.exit(subprocess.call(sys.argv[2:]))
"""


class Job:
    def __init__(self, *, memory, cpu_seconds=None):
        self.handle = create_job(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        # KILL_ON_JOB_CLOSE, JOB_MEMORY and ACTIVE_PROCESS.
        limits.basic.flags = 0x2000 | 0x200 | 0x8
        limits.job_memory = memory
        limits.basic.active_processes = 64
        if cpu_seconds is not None:
            limits.basic.flags |= 0x4  # JOB_TIME in 100 ns user-mode units.
            limits.basic.job_time = cpu_seconds * 10_000_000
        if not set_job(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def start(self, command, **kwargs):
        read, write = os.pipe()
        process = None
        try:
            handle = msvcrt.get_osfhandle(read)
            os.set_handle_inheritable(handle, True)
            startup = subprocess.STARTUPINFO(lpAttributeList={"handle_list": [handle]})
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", GATE, str(handle), *command], startupinfo=startup, **kwargs,
            )
            child = open_process(0x0100 | 0x0001, False, process.pid)
            if not child:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not assign(self.handle, child):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                close(child)
            os.write(write, b"1")
            return process
        except BaseException:
            if process is not None:
                process.kill()
                process.communicate()
            raise
        finally:
            os.close(read)
            os.close(write)

    def close(self):
        close(self.handle)
