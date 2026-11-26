#!/bin/sh
# Inspect prerequisites without changing the host or touching existing guests.
set -eu
uname -sm
free -h
df -h .
lscpu | awk '/^(Architecture|CPU\(s\)|Virtualization):/'
for path in /dev/kvm /dev/net/tun; do
    if test -c "$path"; then ls -l "$path"; else printf '%s absent in this process\n' "$path"; fi
done
docker info --format 'Docker Engine {{.ServerVersion}}'
docker compose version
qemu-system-x86_64 -accel help
docker ps -a --filter ancestor=dockurr/windows --format 'Dockur guest {{.Status}}'
curl --head --silent --show-error --fail --max-time 10 https://www.microsoft.com/en-us/evalcenter/download-windows-11-enterprise >/dev/null
printf 'Microsoft Evaluation Center HTTPS reachable\n'
