$ErrorActionPreference = 'Stop'
$folder = 'C:\HMM-QA'
New-Item -Type Directory -Force $folder | Out-Null
Copy-Item -Force C:\OEM\guest.ps1 "$folder\guest.ps1"
$account = 'HMMQA' + [Environment]::MachineName
$secret = 'Hm!7' + [Guid]::NewGuid().ToString('N')
$secure = ConvertTo-SecureString $secret -AsPlainText -Force
if (-not (Get-LocalUser -Name $account -ErrorAction SilentlyContinue)) {
    New-LocalUser -Name $account -Password $secure -Description 'Local Windows portability test account' | Out-Null
    Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $account
} else {
    Set-LocalUser -Name $account -Password $secure
}
$code = "& ([scriptblock]::Create([IO.File]::ReadAllText('C:\HMM-QA\guest.ps1')))"
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
$credentials = New-Object Management.Automation.PSCredential("$env:COMPUTERNAME\$account", $secure)
Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Credential $credentials -LoadUserProfile -WindowStyle Hidden -WorkingDirectory $folder -ArgumentList "-NoProfile -NonInteractive -EncodedCommand $encoded"
