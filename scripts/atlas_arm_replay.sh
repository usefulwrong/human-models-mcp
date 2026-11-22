#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  printf '%s\n' 'Usage: bash scripts/atlas_arm_replay.sh BASE_BLEND EXPECTED_JSON HD_REFERENCE_BLEND NEW_OUTPUT' >&2
  exit 2
fi

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
base=$(realpath -e -- "$1")
mapping=$(realpath -e -- "$2")
reference=$(realpath -e -- "$3")
mkdir -- "$4"
out=$(realpath -e -- "$4")
mkdir -- "$out"/{hd,distal,repair,render}
image=${HMM_RENDER_IMAGE:-human-models-mcp-night-renderer:local}
isolation=(--rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges
  --cpus 5 --memory 10g --tmpfs /tmp:size=1g,mode=1777 --user "$(id -u):$(id -g)")
gpu=(--gpus all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics
  -e BLENDER_USER_CONFIG=/tmp/blender -e CUDA_CACHE_PATH=/tmp/cuda)

blender() {
  local scene=$1 stage=$2 script=$3
  shift 3
  local devices=()
  local log="$out/$stage.log"
  if [[ $stage == render ]]; then devices=("${gpu[@]}"); fi
  if [[ ${1:-} == verify ]]; then log="$out/reopen.log"; fi
  docker run "${isolation[@]}" "${devices[@]}" -e PYTHONPATH=/code \
    -v "$repo/scripts:/code:ro" -v "$scene:/scene.blend:ro" -v "$mapping:/mapping.json:ro" \
    -v "$reference:/reference.blend:ro" -v "$out/$stage:/out" \
    --entrypoint /opt/blender/blender "$image" -b --disable-autoexec --python-use-system-env \
    /scene.blend --python-exit-code 1 --python "/code/$script" -- /out /mapping.json "$@" \
    > "$log" 2>&1
  printf '%s\n' "$stage"
}

blender "$base" hd atlas_arm_hd_blender.py /reference.blend
blender "$out/hd/arm-hd.blend" distal atlas_arm_fit_blender.py
blender "$out/distal/arm-fit.blend" repair atlas_arm_surface_blender.py
blender "$out/distal/arm-fit.blend" repair atlas_arm_surface_blender.py verify
blender "$out/repair/arm-surfaces.blend" render atlas_arm_review_blender.py arm-motion
docker run "${isolation[@]}" -v "$out/render:/out" --entrypoint ffmpeg "$image" -v error \
  -framerate 5 -i /out/motion-%03d.png -c:v libx264 -pix_fmt yuv420p -movflags +faststart /out/animation.mp4
printf '%s\n' "$out"
