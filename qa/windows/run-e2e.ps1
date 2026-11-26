$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$qa = Join-Path $env:LOCALAPPDATA 'HMM-QA'
$gateway = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1).NextHop
$base = "http://${gateway}:8788"
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_ComputerSystem
"OS=$($os.Caption); Build=$($os.BuildNumber); CPUs=$($cpu.NumberOfLogicalProcessors); RAM=$($cpu.TotalPhysicalMemory)"
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Expected the standard QA account' }
'standard_user=true'
foreach ($name in @('python.exe','node.exe','blender.exe','git.exe','docker.exe')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*\Microsoft\WindowsApps\*') { throw "Clean VM unexpectedly has $name" }
}
$work = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Research Projects'
New-Item -ItemType Directory -Force $work | Out-Null
$zip = Join-Path $qa 'windows-x64.zip'
Invoke-WebRequest -UseBasicParsing "$base/human-models-mcp-0.9.1rc1-windows-x64.zip" -OutFile $zip
$sum = Join-Path $qa 'SHA256SUMS'
Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS" -OutFile $sum
$expected = ((Get-Content -LiteralPath $sum -Encoding UTF8 -First 1) -split '\s+')[0]
if ((Get-FileHash -LiteralPath $zip).Hash -ne $expected) { throw 'Public ZIP checksum differs' }
$deployment = Join-Path $work ('Human Models MCP ' + (Get-Date -Format 'HHmmss'))
if (Test-Path $deployment) { throw 'Test deployment already exists' }
Expand-Archive -LiteralPath $zip -DestinationPath $deployment
$project = Join-Path $deployment 'human-models-mcp-0.9.1rc1-windows-x64'
Set-Content -LiteralPath (Join-Path $qa 'project.txt') -Value $project -Encoding UTF8
$start = New-Object Diagnostics.ProcessStartInfo
$start.FileName = $env:ComSpec
$start.Arguments = '/d /c call "' + $project + '\Start.cmd"'
$start.WorkingDirectory = 'C:\Windows'
$start.UseShellExecute = $false
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.StandardOutputEncoding = [Text.Encoding]::UTF8
$start.StandardErrorEncoding = [Text.Encoding]::UTF8
$process = [Diagnostics.Process]::Start($start)
$stdout = $process.StandardOutput.ReadToEndAsync()
$stderr = $process.StandardError.ReadToEndAsync()
try {
    $process.StandardInput.WriteLine('y')
    $deadline = [DateTime]::UtcNow.AddMinutes(15)
    while (-not $process.HasExited -and -not (Test-Path "$project\.runtime\core.json") -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 1
    }
    if (-not $process.HasExited) {
        $process.StandardInput.WriteLine('2')
        $process.StandardInput.WriteLine('')
        $process.StandardInput.Close()
    }
    if (-not $process.WaitForExit(180000)) { throw 'Interactive Start.cmd did not finish' }
    $stdout.Result
    $stderr.Result
    if ($process.ExitCode) { throw "Start.cmd exited $($process.ExitCode)" }
} finally {
    if (-not $process.HasExited) { $process.Kill() }
    $process.Dispose()
}
& "$project\Start.cmd" config --format toml 2>&1
if ($LASTEXITCODE) { throw 'Configuration generation failed' }
$run = Get-ChildItem -Path "$project\results" -Filter manifest.json -Recurse | Select-Object -First 1
if (-not $run) { throw 'First experiment manifest is missing' }
$manifest = Get-Content -LiteralPath $run.FullName -Encoding UTF8 -Raw | ConvertFrom-Json
if ($manifest.status -ne 'computed' -or $manifest.counts.actuators -ne 700) { throw 'First experiment did not compute with its pinned model' }
'WINDOWS_CLEAN_CORE_PASS'
