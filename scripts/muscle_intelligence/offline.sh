#!/usr/bin/env bash
# Run the staged app in a Docker network namespace with loopback only.
set -Eeuxo pipefail
root=$(pwd -P)
qa=outputs/v09/full-muscles
log=$qa/logs
server="hmm-muscle-audit-$$"
mkdir -p "$qa/browser" "$qa/regression" "$qa/regression-moving" "$log"
trap 'rc=$?; docker logs "$server" > "$log/docker-http.log" 2>&1 || true; docker stop "$server" >/dev/null 2>&1 || true; echo "offline exit=$rc"; exit "$rc"' EXIT
iso=(--read-only --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,exec,size=1g,mode=1777 --user "$(id -u):$(id -g)" -e HOME=/tmp)
docker run -d --rm --name "$server" --pull never --network none "${iso[@]}" -w /work \
  -v "$root:/work:ro" -v "$root/$qa:/work/$qa:rw" --entrypoint bash hmm-v080-final-runtime:local -c \
  'HMM_PYTHON=python HMM_PORT=18946 bash scripts/muscle_intelligence/local.sh'
docker inspect --format '{{.HostConfig.NetworkMode}} {{.Image}}' "$server"
docker exec "$server" python -c 'import errno,socket,time,urllib.request
for i in range(40):
    try:
        assert urllib.request.urlopen("http://127.0.0.1:18946/",timeout=1).status==200
        break
    except OSError: time.sleep(.25)
else: raise SystemExit("local server did not start")
try: socket.create_connection(("192.0.2.1",443),timeout=.4)
except OSError as e:
    print("egress control",e.errno,e)
    assert e.errno in (errno.ENETUNREACH,errno.EHOSTUNREACH)
else: raise AssertionError("unexpected egress")
'
docker exec "$server" bash -c 'source scripts/muscle_intelligence/local.sh
  exec python scripts/muscle_intelligence/transport_check.py http://127.0.0.1:18946 "$HMM_LAB_WORK" --full' \
  > "$log/transport.log" 2>&1
docker run --rm --pull never --gpus all --network "container:$server" "${iso[@]}" --shm-size=1g \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics -e NODE_PATH=/sdk \
  -v "$root/outputs/v09/airgap/browser-sdk:/sdk:ro" -v "$root/scripts/muscle_intelligence:/checks:ro" \
  -v "$root/tests/anatomy_lab_e2e:/regression:ro" \
  -v "$root/outputs/v09/moving-human/clip-final:/clip:ro" \
  -v "$root/outputs/v09/followup/motion/candidate/motion.json:/legacy.json:ro" \
  -v "$root/$qa:/evidence:rw" --entrypoint sh mcr.microsoft.com/playwright:v1.64.1-noble -c '
    nvidia-smi --query-gpu=name,driver_version,memory.used,utilization.gpu --format=csv -lms 500 > /evidence/browser/vram.csv &
    monitor=$!
    trap "kill $monitor 2>/dev/null || true; wait $monitor 2>/dev/null || true" EXIT
    node /checks/browser_check.cjs http://127.0.0.1:18946 /evidence || exit $?
    if [ "${1:-}" = regressions ]; then
      HMM_BROWSER_GPU=1 node /regression/browser.cjs http://127.0.0.1:18946 /evidence/regression "" /legacy.json
      node /regression/moving.cjs http://127.0.0.1:18946 /evidence/regression-moving /clip/samples.json
    fi
  ' -- "${1:-}" > "$log/desktop-mobile.log" 2>&1
