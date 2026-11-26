$ErrorActionPreference = 'Stop'
# QEMU slirp's host alias routes to the isolated test container.
$gateway = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1).NextHop
$base = "http://${gateway}:8788"
$qa = Join-Path $env:LOCALAPPDATA 'HMM-QA'
New-Item -ItemType Directory -Force $qa | Out-Null
$ready = Join-Path $qa 'ready.txt'
[IO.File]::WriteAllText($ready, 'standard guest worker ready')
Invoke-WebRequest -UseBasicParsing -Method Put -InFile $ready "$base/4444444444444444.log" | Out-Null
$seen = ''
while ($true) {
    try {
        $id = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "$base/request.txt").Content.Trim()
        if ($id -match '^[0-9a-f]{16}$' -and $id -ne $seen) {
            $seen = $id
            $script = (Invoke-WebRequest -UseBasicParsing "$base/$id.ps1").Content
            if ($script -is [byte[]]) { $script = [Text.Encoding]::UTF8.GetString($script) }
            $log = Join-Path $qa "$id.log"
            & {
                try { & ([scriptblock]::Create($script)) }
                catch { $_ | Out-String; 'QA_ACTION_FAILED' }
            } *> $log
            Invoke-WebRequest -UseBasicParsing -Method Put -InFile $log "$base/$id.log" | Out-Null
        }
    } catch { }
    Start-Sleep -Seconds 3
}
