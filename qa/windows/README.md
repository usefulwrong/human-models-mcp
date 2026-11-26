# Windows 11 acceptance VM

The stand uses the pinned dockur/windows 6.06 amd64 image with a 100 GiB
sparse disk, 6 vCPUs, 12 GiB RAM, a virtual TPM and QEMU user-mode networking.
Host console ports bind to loopback. The VM uses a Microsoft Enterprise LTSC
Evaluation ISO. Activate the evaluation using Windows' normal activation
process. Keep the ISO outside any distributable archive.
[Microsoft Evaluation Center](https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise)

Run from the Linux checkout. Use a fresh work directory. The KVM override
passes only the KVM device and can be omitted for QEMU TCG.

```sh
export HMM_QA_ROOT="$PWD/.cache/windows-qa"
mkdir -p "$HMM_QA_ROOT"/{vm,oem,share}
cp qa/windows/install.bat qa/windows/{prepare,guest}.ps1 "$HMM_QA_ROOT/oem/"
cp qa/windows/host.py "$HMM_QA_ROOT/share/"
# Put the verified Evaluation ISO at "$HMM_QA_ROOT/enterprise-ltsc.iso".
# Supply a new guest-only administrator password in HMM_QA_PASSWORD.
docker compose -p hmm-windows-qa -f qa/windows/compose.yaml -f qa/windows/kvm.yaml up -d
docker compose -p hmm-windows-qa -f qa/windows/compose.yaml -f qa/windows/kvm.yaml exec -d windows sh -c 'cd /shared && python3 host.py'
```

Open the console at `http://127.0.0.1:18006/`. The OEM setup starts the guest
test agent with a standard local account. The agent retrieves operator-owned
test scripts from the isolated container's QEMU host alias. Put both public
ZIP and checksum in the share, copy `run-e2e.ps1` to a new sixteen-digit
hexadecimal filename with the `.ps1` extension, and publish that identifier in
`request.txt`. Look for the matching `.log`. Keep the share private because
the guest executes those local test instructions. Record only sanitized logs.

`scripts/native_acceptance.py` exercises the installed SDK. Add `--renderer`
after installing Renderer. `browser_acceptance.py` requires the installed
Explorer and Playwright development wheels. Use `--motion` when approved local
MotionScene assets and a matching crosswalk are attached. The console may be
captured independently through the QEMU monitor. Browser screenshots come from
Playwright desktop and mobile contexts.

For air-gap testing, stage the verified cache in the guest, disconnect this
VM's dedicated Docker network, confirm that an external HTTPS request fails
inside the guest, and repeat installation using `HMM_OFFLINE_CACHE`.
The QEMU loopback file shuttle stays inside the VM container.

When testing finishes, use `docker compose ... stop` with the same project
and files. The local disk and logs can be reused with the same test secrets.

Run `sh qa/windows/preflight.sh` to check host-visible devices, Docker,
available resources and evaluation media connectivity. The Docker daemon
can provide KVM through the override even if the current shell has a
different device view.
