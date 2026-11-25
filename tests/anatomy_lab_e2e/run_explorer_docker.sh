#!/bin/bash
# Run from the project root, using existing local images and a disposable evidence directory.
set -euo pipefail
[[ $# == 4 ]] || { echo "usage: $0 INSTALLED_ATLAS STAGED_WORKDIR PLAYWRIGHT_SDK SOURCE_CACHE"; exit 2; }
atlas=$(realpath "$1"); work=$(realpath "$2"); sdk=$(realpath "$3"); cache=$(realpath "$4")
mkdir -p "$work/docker/browser" "$work/docker/explorer" "$work/docker/transport"
server="hmm-explorer-audit-$$"
isolation=(--read-only --cap-drop ALL --security-opt no-new-privileges:true
  --tmpfs /tmp:rw,exec,size=1g,mode=1777 --user "$(id -u):$(id -g)" -e HOME=/tmp)
trap 'docker logs "$server" > "$work/docker/http.log" 2>&1 || true; docker stop "$server" >/dev/null 2>&1 || true' EXIT
set -x
docker run --rm -d --name "$server" --pull never --network none "${isolation[@]}" \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/work/src:/work/scripts/anatomy_lab \
  -e HMM_LAB_CATALOG=/atlas/catalog.json -e HMM_LAB_SITE=/workspace/candidate/site \
  -v "$PWD:/work:ro" -v "$atlas:/atlas:ro" -v "$work:/workspace:rw" -v "$cache:/cache:ro" \
  --entrypoint python hmm-v080-final-runtime:local -m lab_web --port 18943
docker exec -d -e PYTHONPATH=/workspace/baseline/code:/work/src -e HMM_LAB_SITE=/workspace/baseline/site \
  "$server" sh -c 'exec python -m lab_web --port 18945 > /workspace/docker/baseline-http.log 2>&1'
docker inspect --format '{{.HostConfig.NetworkMode}}' "$server"
docker exec "$server" sh -c 'cat /proc/net/dev; cat /proc/net/route'
docker exec "$server" python -c 'import errno,socket
try:
    socket.create_connection(("192.0.2.1",443),timeout=.4)
except OSError as e:
    print("egress control",e.errno,e)
    assert e.errno in (errno.ENETUNREACH,errno.EHOSTUNREACH)
else:
    raise AssertionError("external route present")
'
docker exec "$server" python -c 'import time,urllib.request
for port in (18943,18945):
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/",timeout=1) as r:
                assert r.status == 200
            break
        except OSError:
            time.sleep(.25)
    else:
        raise SystemExit(f"server unavailable: {port}")
'
docker run --rm --pull never --gpus all --network "container:$server" "${isolation[@]}" --shm-size=1g \
  -e NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics -e NODE_PATH=/sdk -e HMM_BROWSER_GPU=1 \
  -v "$sdk:/sdk:ro" -v "$PWD/tests/anatomy_lab_e2e:/checks:ro" \
  -v "$work/docker:/evidence:rw" -v "$work/baseline/scenes/FMA7088-desktop.json:/matched.json:ro" \
  --entrypoint sh mcr.microsoft.com/playwright:v1.64.1-noble -c '
    nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv -lms 500 > /evidence/browser-vram.csv &
    monitor=$!
    trap "kill $monitor 2>/dev/null || true; wait $monitor 2>/dev/null || true" EXIT
    node /checks/browser.cjs http://127.0.0.1:18943 /evidence/browser
    a=$?
    HMM_SKIP_BENCHMARK=1 node /checks/explorer.cjs http://127.0.0.1:18943 http://127.0.0.1:18945 /evidence/explorer /matched.json
    b=$?
    HMM_BENCHMARK_ONLY=1 node /checks/explorer.cjs http://127.0.0.1:18943 http://127.0.0.1:18945 /evidence/explorer /matched.json
    c=$?
    echo "browser_exit=$a explorer_exit=$b benchmark_exit=$c"
    test "$a$b$c" = 000
  '
docker restart "$server"
docker exec "$server" python -c 'import time, urllib.request
for _ in range(80):
    try:
        with urllib.request.urlopen("http://127.0.0.1:18943/", timeout=1) as r:
            assert r.status == 200
        break
    except OSError:
        time.sleep(.25)
else:
    raise SystemExit("restart did not restore local HTTP")
'
docker exec "$server" python /work/tests/anatomy_lab_e2e/transports.py --source-cache /cache \
  --output /workspace/docker/transport --scene-dir /workspace/docker/browser/scenes \
  --explorer-scene /workspace/docker/explorer/scenes/left-lung-explorer.json
