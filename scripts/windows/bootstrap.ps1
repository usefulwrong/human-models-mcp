$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = $env:HMM_BOOTSTRAP_ROOT
$runtime = Join-Path $root '.runtime'
if ([Environment]::OSVersion.Platform -ne 'Win32NT' -or
    ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64')) {
    throw 'The bootstrap supports Windows x64.'
}
if (Test-Path (Join-Path $runtime 'python\hmm-python-ready')) { return }
$null = New-Item -ItemType Directory -Force $runtime
if ((Get-Item -LiteralPath $runtime).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'The runtime folder cannot be a junction or symlink.'
}
$lock = [IO.File]::Open((Join-Path $runtime 'bootstrap.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
$temp = Join-Path $runtime ('python-' + [Guid]::NewGuid().ToString('N'))
try {
    if (Test-Path (Join-Path $runtime 'python\hmm-python-ready')) { return }
    $pins = Get-Content -LiteralPath (Join-Path $root 'dependencies-windows-x64.json') -Encoding UTF8 -Raw | ConvertFrom-Json
    $cache = $env:HMM_OFFLINE_CACHE
    if (-not $cache) { $cache = Join-Path $runtime 'cache' }
    $null = New-Item -ItemType Directory -Force $cache
    Write-Host 'Core installation starts with portable CPython 3.12.10 and pip (about 13 MB download).'
    Write-Host 'Core uses about 125 MB of downloads in total. Allow at least 1 GB free for Core.'
    if ($env:HMM_ASSUME_YES -ne '1' -and (Read-Host 'Continue [y/N]') -notmatch '^[yY]$') {
        throw 'Installation cancelled.'
    }
    $log = Join-Path $runtime 'install.log'
    function Get-Verified($item) {
        $file = Join-Path $cache ([IO.Path]::GetFileName(([Uri]$item.url).AbsolutePath))
        if (Test-Path -LiteralPath $file) {
            if ((Get-Item -LiteralPath $file).Length -ne $item.bytes -or
                (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $item.sha256) {
                throw ('Cached file is damaged. Move it out of the cache and retry: ' + $file)
            }
        } else {
            if ($env:HMM_OFFLINE_CACHE) { throw ('Required file absent from offline cache: ' + $file) }
            Write-Host ("Downloading " + [IO.Path]::GetFileName($file))
            $part = "$file.part"
            (New-Object Net.WebClient).DownloadFile($item.url, $part)
            if ((Get-Item -LiteralPath $part).Length -ne $item.bytes -or
                (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash -ne $item.sha256) {
                throw ('Downloaded bytes do not match the locked SHA-256: ' + $file)
            }
            [IO.File]::Move($part, $file)
        }
        Add-Content -LiteralPath $log -Value ("Verified " + [IO.Path]::GetFileName($file)) -Encoding UTF8
        return $file
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $python = Get-Verified $pins.python
    $pip = Get-Verified $pins.pip
    [IO.Compression.ZipFile]::ExtractToDirectory($python, $temp)
    $site = Join-Path $temp 'Lib\site-packages'
    [IO.Compression.ZipFile]::ExtractToDirectory($pip, $site)
    [IO.File]::WriteAllLines((Join-Path $temp 'python312._pth'),
        @('python312.zip', '.', 'Lib\site-packages', '..\..\src', '..\..\scripts', '..\..\scripts\anatomy_lab', '..\..\examples\mcp-client', 'import site'))
    & (Join-Path $temp 'python.exe') -X utf8 -m pip --version
    if ($LASTEXITCODE -ne 0) { throw 'Portable Python smoke test failed.' }
    [IO.File]::WriteAllText((Join-Path $temp 'hmm-python-ready'), $pins.python.sha256)
    [IO.Directory]::Move($temp, (Join-Path $runtime 'python'))
} catch {
    Add-Content -LiteralPath (Join-Path $runtime 'install.log') -Value ('Bootstrap failed: ' + $_.Exception.Message) -Encoding UTF8
    throw
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force }
    $lock.Dispose()
}
