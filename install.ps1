[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'CaelestiaYASB'),
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

if ((Get-CimInstance Win32_Processor | Select-Object -First 1).Architecture -ne 9 -or
    [Environment]::OSVersion.Version.Build -lt 22000) {
    throw 'This build requires Windows 11 on an x64 PC.'
}
if (Test-Path -LiteralPath $InstallDir) {
    throw "The destination already exists. Choose a new -InstallDir to keep the existing copy safe: $InstallDir"
}

function Get-VerifiedFile($Artifact, [string]$Destination) {
    Write-Host "Downloading $($Artifact.name)"
    & curl.exe --fail --silent --show-error --location --retry 2 --output $Destination $Artifact.url
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed: $($Artifact.name)"
    }
    if ((Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash -ne $Artifact.sha256) {
        throw "SHA-256 verification failed: $($Artifact.name)"
    }
}

$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'dependencies.json') -Raw | ConvertFrom-Json
$parent = Split-Path -Parent $InstallDir
New-Item -ItemType Directory -Force -Path $parent | Out-Null
$tempName = '.cysb-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$scratch = [IO.Path]::GetFullPath((Join-Path $parent $tempName))
New-Item -ItemType Directory -Path $scratch | Out-Null
try {
    $downloads = Join-Path $scratch 'downloads'
    $stage = Join-Path $scratch 'install'
    New-Item -ItemType Directory -Path $downloads, $stage | Out-Null
    $msi = Join-Path $downloads $lock.yasb.name
    $pythonZip = Join-Path $downloads $lock.python.name
    Get-VerifiedFile $lock.yasb $msi
    Get-VerifiedFile $lock.python $pythonZip
    foreach ($wheel in $lock.wheels) {
        Get-VerifiedFile $wheel (Join-Path $downloads $wheel.name)
    }

    Write-Host 'Extracting the portable YASB and Python runtimes'
    $yasb = Join-Path $stage 'yasb'
    $python = Join-Path $stage 'python'
    $arguments = '/a "{0}" /qn /norestart TARGETDIR="{1}"' -f $msi, $yasb
    $extractor = Start-Process -FilePath "$env:WINDIR\System32\msiexec.exe" -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($extractor.ExitCode -ne 0 -or !(Test-Path -LiteralPath (Join-Path $yasb 'yasb.exe'))) {
        throw "YASB extraction failed. Windows Installer returned $($extractor.ExitCode)."
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($pythonZip, $python)
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config') -Destination $stage -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'start.cmd') -Destination $stage
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'licenses') -Destination $stage -Recurse
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'LICENSE') -Destination $stage

    $withKomorebi = [bool](Get-Command komorebic.exe -ErrorAction SilentlyContinue)
    $mode = if ($withKomorebi) { 'komorebi' } else { 'standard' }
    & (Join-Path $python 'python.exe') (Join-Path $PSScriptRoot 'tools\prepare.py') $stage $downloads $mode
    if ($LASTEXITCODE -ne 0) {
        throw 'Preparing the portable configuration failed.'
    }
    [IO.Directory]::Move($stage, $InstallDir)
} finally {
    # Only remove the freshly created staging directory in the intended parent.
    if ((Split-Path -Parent $scratch) -eq $parent -and
        (Split-Path -Leaf $scratch) -eq $tempName -and
        (Test-Path -LiteralPath $scratch -PathType Container)) {
        Remove-Item -LiteralPath $scratch -Recurse -Force
    }
}

if (!$NoStart) {
    $programs = [Environment]::GetFolderPath('Programs')
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $programs 'Start Caelestia YASB.lnk'))
    $shortcut.TargetPath = Join-Path $InstallDir 'start.cmd'
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.IconLocation = (Join-Path $InstallDir 'yasb\yasb.exe') + ',0'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
    if (Get-Process -Name yasb -ErrorAction SilentlyContinue) {
        Write-Host 'Quit the running YASB from its tray menu, then open Start Caelestia YASB.'
    } else {
        Start-Process -FilePath (Join-Path $InstallDir 'start.cmd') -WindowStyle Hidden
    }
}
Write-Host "Caelestia YASB is ready in $InstallDir"
