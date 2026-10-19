$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ([Environment]::Is64BitOperatingSystem -ne $true) { throw '64-bit Windows 10/11 required.' }
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Windows ARM64 is not packaged or tested. Use x64 Windows, or import a transcript in the basic app.' }
$lectureConsent = Read-Host 'Download and install only in this folder? [y/N]'
if ($lectureConsent -notmatch '^[yY]$') { exit 1 }
$lecturePython = Join-Path $PSScriptRoot '.portable\python\python.exe'
if (-not (Test-Path $lecturePython)) {
    $lectureManifest = Get-Content -Raw (Join-Path $PSScriptRoot 'portable_runtime.json') | ConvertFrom-Json
    $lectureRuntime = $lectureManifest.'windows-x86_64'
    New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot '.portable') | Out-Null
    $lectureArchive = Join-Path $PSScriptRoot '.portable\python-download.tar.gz'
    Invoke-WebRequest -Uri $lectureRuntime.url -OutFile $lectureArchive -UseBasicParsing
    if ((Get-FileHash -Algorithm SHA256 $lectureArchive).Hash.ToLower() -ne $lectureRuntime.sha256) { throw 'Python checksum mismatch; stopped.' }
    if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) { throw 'Windows tar.exe required. Update Windows or install Python 3.12 from python.org, then ask Codex to read CODEX_SETUP.md.' }
    & tar.exe -xzf $lectureArchive -C (Join-Path $PSScriptRoot '.portable')
    if ($LASTEXITCODE -ne 0) { throw 'Python archive extraction failed.' }
}
& $lecturePython bootstrap.py --install
if ($LASTEXITCODE -ne 0) { throw 'Setup incomplete; the basic app can still be started without the model.' }
