"""Local subprocess containment for trusted workers and renderer tools."""

from contextlib import contextmanager
import os
import subprocess

if os.name == "nt":
    from .windows_job import Job
else:
    import ctypes
    import resource
    import signal


def linux_child_limits(cpu_seconds):
    if os.name == "nt":
        return
    if "HMM_PARENT_PID" in os.environ:
        parent_death(int(os.environ["HMM_PARENT_PID"]))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds - 5, cpu_seconds))


def parent_death(parent_pid):
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot enforce worker parent-death signal")
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def process_group(parent_pid):
    os.setsid()
    parent_death(parent_pid)


def stop_group(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


@contextmanager
def managed_process(command, *, memory, cpu_seconds=None, linux_group=False, **kwargs):
    if os.name == "nt":
        job = Job(memory=memory, cpu_seconds=cpu_seconds)
        try:
            with job.start(command, **kwargs) as process:
                try:
                    yield process
                finally:
                    job.close()
        finally:
            # Job assignment errors must also dispose of the handle.
            if "process" not in locals():
                job.close()
    else:
        if linux_group:
            parent_pid = os.getpid()
            kwargs["preexec_fn"] = lambda: process_group(parent_pid)
        with subprocess.Popen(command, **kwargs) as process:
            try:
                yield process
            finally:
                if linux_group:
                    stop_group(process)
                elif process.poll() is None:
                    process.kill()


def science_cpu_seconds(request):
    articulated = (request["operation"] == "pushup"
                   and request["parameters"].get("contact_profile") == "articulated_palms_v1")
    return 75 if articulated else 50
