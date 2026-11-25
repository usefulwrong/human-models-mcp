import bpy
import subprocess
from pathlib import Path
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "CUDA"
prefs.refresh_devices()
devices = [d for d in prefs.devices if d.type == "CUDA"]
assert devices, "Cycle CUDA devices unavailable"
for d in prefs.devices:
    d.use = d.type == "CUDA"
print("CUDA devices", [(d.name, d.type, d.use) for d in prefs.devices], flush=True)
s = bpy.context.scene
s.render.engine = "CYCLES"
s.cycles.device = "GPU"
s.cycles.samples = 16
s.render.resolution_x = s.render.resolution_y = 384
s.render.resolution_percentage = 100
s.render.filepath = "/tmp/cuda-scene.png"
probe = subprocess.Popen(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv", "-lms", "250"])
try:
    bpy.ops.render.render(write_still=True)
    assert Path(s.render.filepath).stat().st_size > 0
    print("CUDA render bytes", Path(s.render.filepath).stat().st_size, flush=True)
finally:
    probe.terminate()
    probe.wait()
