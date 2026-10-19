param(
    [ValidateSet('basic', 'pdf', 'speech', 'full')][string]$Profile = 'basic',
    [switch]$Yes,
    [switch]$NoLaunch
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows 10/11 required.' }
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    throw 'Windows ARM64 is not packaged. Use a supported Python installation for the basic app.'
}
Write-Host 'Lecture Atelier - Setup'
if (-not $PSBoundParameters.ContainsKey('Profile') -and -not $Yes) {
    Write-Host '1 Basic (no speech model) [default] | 2 PDF | 3 Local Whisper | 4 PDF + Whisper'
    $lectureChoice = Read-Host 'Choose [1]'
    switch ($lectureChoice) {
        '' { $Profile = 'basic' }; '1' { $Profile = 'basic' }; '2' { $Profile = 'pdf' }
        '3' { $Profile = 'speech' }; '4' { $Profile = 'full' }
        default { throw 'Invalid setup selection.' }
    }
}
$lectureVersionCheck = 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] else 1)'
if ($Profile -ne 'basic') {
    $lectureVersionCheck = 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)'
}
$lecturePortable = Join-Path $PSScriptRoot '.portable\python\python.exe'
$lecturePython = $null
$lecturePrefix = @()
$lectureCandidates = @(
    @{File=$lecturePortable; Args=@()},
    @{File='py'; Args=@('-3.12')},
    @{File='py'; Args=@('-3')},
    @{File='python'; Args=@()}
)
foreach ($lectureCandidate in $lectureCandidates) {
    $lectureFile = $lectureCandidate.File
    $lectureArgs = $lectureCandidate.Args
    $lectureResolved = Get-Command $lectureFile -ErrorAction SilentlyContinue
    if ($lectureResolved -and $lectureResolved.Source -notmatch '\\WindowsApps\\') {
        & $lectureFile @lectureArgs -c $lectureVersionCheck 2>$null
        if ($LASTEXITCODE -eq 0) {
            $lecturePython = $lectureFile; $lecturePrefix = $lectureArgs; break
        }
    }
}
if (-not $lecturePython -or $Profile -ne 'basic') {
    Write-Host "Selected profile: $Profile. Downloads stay in this project; no recordings are uploaded."
    if ($Profile -eq 'basic') { Write-Host 'Only a pinned Python runtime will be downloaded; no speech model.' }
    elseif ($Profile -eq 'pdf') { Write-Host 'PDF dependencies only. Python is downloaded only if needed.' }
    else { Write-Host 'Whisper setup may need 0.5-1.5 GB downloads and 2-4 GB disk. Existing speech settings are retained.' }
    if (-not $Yes) {
        $lectureConsent = Read-Host 'Download and install only in this folder? [y/N]'
        if ($lectureConsent -notmatch '^[yY]$') { exit 1 }
    }
}
if (-not $lecturePython) {
    $lectureRuntimeDir = Join-Path $PSScriptRoot '.portable\python'
    $lecturePortableDir = Join-Path $PSScriptRoot '.portable'
    if (Test-Path $lectureRuntimeDir) { throw 'Existing local runtime is incompatible; nothing was overwritten.' }
    if ((Test-Path $lecturePortableDir) -and ((Get-Item $lecturePortableDir -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Runtime directory cannot be a symbolic link or junction.'
    }
    $lectureManifest = Get-Content -Raw (Join-Path $PSScriptRoot 'portable_runtime.json') | ConvertFrom-Json
    $lectureRuntime = $lectureManifest.'windows-x86_64'
    New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot '.portable') | Out-Null
    $lectureArchive = Join-Path $PSScriptRoot '.portable\python-download.tar.gz'
    Invoke-WebRequest -Uri $lectureRuntime.url -OutFile $lectureArchive -UseBasicParsing
    if ((Get-FileHash -Algorithm SHA256 $lectureArchive).Hash.ToLower() -ne $lectureRuntime.sha256) { throw 'Python checksum mismatch; stopped.' }
    if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) { throw 'Windows tar.exe required. Update Windows or install Python 3.12 from python.org, then ask Codex to read CODEX_SETUP.md.' }
    & tar.exe -xzf $lectureArchive -C (Join-Path $PSScriptRoot '.portable')
    if ($LASTEXITCODE -ne 0) { throw 'Python archive extraction failed.' }
    $lecturePython = $lecturePortable
    $lecturePrefix = @()
}
& $lecturePython @lecturePrefix bootstrap.py --install --profile $Profile
if ($LASTEXITCODE -ne 0) { throw 'Optional setup incomplete. The basic app can still be opened with launch-windows.bat.' }
if (-not $NoLaunch) {
    $env:PYTHONPATH = (Join-Path $PSScriptRoot '.portable\vendor') + [IO.Path]::PathSeparator + $env:PYTHONPATH
    & $lecturePython @lecturePrefix app.py --open
    exit $LASTEXITCODE
}
