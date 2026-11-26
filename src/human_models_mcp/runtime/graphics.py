"""Select MuJoCo's rendering backend before the native import."""

import os


def requested_backend(render=True):
    if os.name == "nt":
        return os.environ.get("MUJOCO_GL", "glfw") if render else "disable"
    return os.environ.get("MUJOCO_GL", "osmesa")


def actual_backend(vendor):
    backend = requested_backend()
    if backend == "egl" and "NVIDIA" in vendor:
        return "nvidia_egl"
    return "glfw" if os.name == "nt" else backend
