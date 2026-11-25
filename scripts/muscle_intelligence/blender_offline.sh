#!/usr/bin/env bash
set -Eeuxo pipefail
qa=outputs/v09/full-muscles
log=$qa/logs
opts=(--rm --pull never --network none --read-only --cap-drop ALL --security-opt no-new-privileges
  --tmpfs /tmp:rw,exec,size=1g,mode=1777 --user "$(id -u):$(id -g)" -e HOME=/tmp
  -e PYTHONDONTWRITEBYTECODE=1 -e CUDA_CACHE_PATH=/tmp/cuda -e OPENBLAS_NUM_THREADS=1
  -v "$PWD/scripts:/work/scripts:ro" -v "$PWD/$qa/blender:/render:rw")
image=hmm-v080-final-renderer:local
pipeline=(--disable-autoexec --python-exit-code 1 --python /work/scripts/muscle_intelligence/blender_muscles.py)
docker run "${opts[@]}" --entrypoint /opt/blender/blender "$image" \
  -b -t 4 /render/muscle-intelligence.blend "${pipeline[@]}" -- reopen /render > "$log/blender-reopen.log" 2>&1
echo "exit=$?" >> "$log/blender-reopen.log"
for mode in pilot dq regions render; do
  extra=()
  args=(/render)
  if [[ $mode == pilot || $mode == dq ]]; then
    extra=(-v "$PWD/$qa/endpoints.json:/endpoints.json:ro")
    args+=(/endpoints.json)
  fi
  docker run "${opts[@]}" "${extra[@]}" --gpus all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics \
    --entrypoint sh "$image" -c '
      nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv -lms 500 > "/render/vram-$1.csv" &
      gpu_monitor=$!
      trap "kill $gpu_monitor 2>/dev/null || true; wait $gpu_monitor 2>/dev/null || true" EXIT
      /opt/blender/blender -b -t 4 /render/muscle-intelligence.blend --disable-autoexec --python-exit-code 1 \
        --python /work/scripts/muscle_intelligence/blender_muscles.py -- "$@"
    ' -- "$mode" "${args[@]}" > "$log/blender-$mode.log" 2>&1
  echo "exit=$?" >> "$log/blender-$mode.log"
done
