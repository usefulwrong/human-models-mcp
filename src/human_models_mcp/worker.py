"""One trusted operation per bounded subprocess. stdout is internal JSON only."""

import json
import resource
import sys
import os
import ctypes
import signal


def main():
    if "HMM_PARENT_PID" in os.environ:
        if ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise RuntimeError("cannot enforce worker parent-death signal")
        if os.getppid() != int(os.environ["HMM_PARENT_PID"]):
            raise SystemExit("executor exited before worker startup")
    resource.setrlimit(resource.RLIMIT_CPU, (45, 50))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    # Address space is bounded by Docker's memory limit; Mesa reserves large virtual ranges.
    request = json.load(sys.stdin)
    try:
        from .catalog import model_card
        card = model_card(verify=True, model_id=request.get("model_id", "ms_human_700"))
        if card["status"] != "available":
            result = {"status": card["status"], "error": {"code": card["status"], "message": "model integrity or engine version check failed"}}
        else:
            from .adapters.mujoco import inspect_model, sweep
            from .results import run_dir
            if request["operation"] == "inspect":
                result = inspect_model(request.get("joint"), request.get("model_id", "ms_human_700"))
            elif request["operation"] == "joint_sweep":
                result = sweep(request["parameters"], run_dir(request["run_id"]), request["validation"], request["defaults"])
            elif request["operation"] == "activation_forward":
                from .adapters.forward import forward
                result = forward(request["parameters"], run_dir(request["run_id"]), request["validation"])
            elif request["operation"] == "loaded_elbow":
                from .adapters.loaded import loaded_elbow
                result = loaded_elbow(request["parameters"], run_dir(request["run_id"]), request["validation"])
            elif request["operation"] == "elbow_tracking":
                from .adapters.loaded import loaded_elbow
                result = loaded_elbow(request["parameters"], run_dir(request["run_id"]), request["validation"], tracking=True)
            elif request["operation"] == "wrist_benchmark":
                from .adapters.wrist import benchmark
                result = benchmark(request["parameters"], run_dir(request["run_id"]), request["validation"])
            elif request["operation"] == "pushup":
                from .adapters.pushup import simulate_pushup
                result = simulate_pushup(request["parameters"], run_dir(request["run_id"]), request["validation"])
            elif request["operation"] in ("standing_contact_probe", "assisted_stance"):
                from .adapters.contact import simulate_contact
                result = simulate_contact(request["parameters"], run_dir(request["run_id"]), request["validation"], assisted=request["operation"] == "assisted_stance")
            else:
                raise ValueError("untrusted backend")
        print(json.dumps(result, allow_nan=False))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": {"code": "engine_error", "message": str(exc)[:1500]}}))


if __name__ == "__main__":
    main()
