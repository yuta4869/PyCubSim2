[CmdletBinding()]
param(
    [string]$Python = $env:PYTHON,
    [string]$IsccPath = $env:ISCC_PATH,
    [switch]$TestInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "Windows packages must be built on Windows."
}

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SourcePlist = Join-Path $ProjectDir "PyCubSim2.app\Contents\Info.plist"
$SpecFile = Join-Path $ProjectDir "packaging\PyCubSim2.windows.spec"
$IconSource = Join-Path $ProjectDir "assets\PyCubSim2-app-icon.png"
$BuildRoot = Join-Path $ProjectDir "build\windows"
$PyInstallerDist = Join-Path $BuildRoot "pyinstaller-dist"
$WorkRoot = Join-Path $BuildRoot "work"
$DistRoot = Join-Path $ProjectDir "dist"

if ([string]::IsNullOrWhiteSpace($Python)) {
    $PythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -eq $PythonCommand) {
        throw "python.exe was not found. Install 64-bit Python 3.10 first."
    }
    $Python = $PythonCommand.Source
}

& $Python -c "import PyInstaller, PIL"
if ($LASTEXITCODE -ne 0) {
    throw (
        "Build dependencies are missing. Run: " +
        "$Python -m pip install -r requirements.txt -r requirements-build.txt"
    )
}

$Version = (
    & $Python -c (
        "import plistlib,sys; " +
        "print(plistlib.load(open(sys.argv[1], 'rb'))" +
        "['CFBundleShortVersionString'])"
    ) $SourcePlist
).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
    throw "Could not read the PyCubSim2 version."
}

$BuildIcon = Join-Path $BuildRoot "PyCubSim2.ico"
$VersionFile = Join-Path $BuildRoot "version_info.txt"
$PyInstallerApp = Join-Path $PyInstallerDist "PyCubSim2"
$PyInstallerExe = Join-Path $PyInstallerApp "PyCubSim2.exe"
$PyInstallerCli = Join-Path $PyInstallerApp "PyCubSim2-cli.exe"
$PortableDir = Join-Path $DistRoot "PyCubSim2-$Version-windows-x64"
$PortableZip = "$PortableDir.zip"
$InstallerPath = Join-Path $DistRoot (
    "PyCubSim2-$Version-windows-x64-setup.exe"
)
$ChecksumPath = Join-Path $DistRoot (
    "PyCubSim2-$Version-windows-x64.sha256"
)
$SmokeImage = Join-Path $BuildRoot "standalone-smoke.png"

Remove-Item $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $PortableDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $PortableZip -Force -ErrorAction SilentlyContinue
Remove-Item $InstallerPath -Force -ErrorAction SilentlyContinue
Remove-Item $ChecksumPath -Force -ErrorAction SilentlyContinue
New-Item $BuildRoot -ItemType Directory -Force | Out-Null
New-Item $PyInstallerDist -ItemType Directory -Force | Out-Null
New-Item $WorkRoot -ItemType Directory -Force | Out-Null
New-Item $DistRoot -ItemType Directory -Force | Out-Null

& $Python (Join-Path $ProjectDir "tools\generate_platform_icons.py") `
    --source $IconSource `
    --ico $BuildIcon
if ($LASTEXITCODE -ne 0) {
    throw "Windows icon generation failed."
}

$VersionParts = @($Version.Split(".") | ForEach-Object { [int]$_ })
while ($VersionParts.Count -lt 4) {
    $VersionParts += 0
}
$VersionParts = @($VersionParts[0..3])
$VersionTuple = $VersionParts -join ", "
$FileVersion = $VersionParts -join "."
$VersionResource = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($VersionTuple),
    prodvers=($VersionTuple),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'yuta4869'),
          StringStruct('FileDescription', 'PyCubSim2 robot simulator'),
          StringStruct('FileVersion', '$FileVersion'),
          StringStruct('InternalName', 'PyCubSim2'),
          StringStruct('LegalCopyright', 'PyCubSim2 contributors'),
          StringStruct('OriginalFilename', 'PyCubSim2.exe'),
          StringStruct('ProductName', 'PyCubSim2'),
          StringStruct('ProductVersion', '$FileVersion')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
Set-Content -Path $VersionFile -Value $VersionResource -Encoding Ascii

$env:PYCUBSIM2_WINDOWS_ICON = $BuildIcon
$env:PYCUBSIM2_VERSION_FILE = $VersionFile
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $PyInstallerDist `
    --workpath $WorkRoot `
    $SpecFile
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed."
}

function Sign-Artifact {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($env:SIGNTOOL_PATH)) {
        return
    }
    if ([string]::IsNullOrWhiteSpace($env:WINDOWS_CERT_SHA1)) {
        throw "WINDOWS_CERT_SHA1 is required when SIGNTOOL_PATH is set."
    }
    & $env:SIGNTOOL_PATH sign `
        /sha1 $env:WINDOWS_CERT_SHA1 `
        /fd SHA256 `
        /tr "http://timestamp.digicert.com" `
        /td SHA256 `
        $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed for $Path."
    }
}

Sign-Artifact -Path $PyInstallerExe
Sign-Artifact -Path $PyInstallerCli

$AgentManifest = Join-Path $PyInstallerApp (
    "_internal\examples\agents\beacon_agent\agent.json"
)
& $PyInstallerCli `
    --headless `
    --steps 5 `
    --agent $AgentManifest `
    --output $SmokeImage
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $SmokeImage)) {
    throw "The standalone Windows smoke test failed."
}

Copy-Item $PyInstallerApp $PortableDir -Recurse
Compress-Archive -Path $PortableDir -DestinationPath $PortableZip `
    -CompressionLevel Optimal

if ([string]::IsNullOrWhiteSpace($IsccPath)) {
    $IsccCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($null -ne $IsccCommand) {
        $IsccPath = $IsccCommand.Source
    }
}
if ([string]::IsNullOrWhiteSpace($IsccPath)) {
    $Candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 7\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    $IsccPath = $Candidates |
        Where-Object { Test-Path $_ } |
        Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($IsccPath) -or -not (Test-Path $IsccPath)) {
    throw (
        "Inno Setup was not found. Install it or set ISCC_PATH. " +
        "The portable ZIP was created at $PortableZip."
    )
}

& $IsccPath `
    "/DMyAppVersion=$Version" `
    "/DMySourceDir=$PortableDir" `
    "/DMyOutputDir=$DistRoot" `
    "/DMyIcon=$BuildIcon" `
    (Join-Path $ProjectDir "packaging\windows\PyCubSim2.iss")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $InstallerPath)) {
    throw "Inno Setup failed."
}
Sign-Artifact -Path $InstallerPath

if ($TestInstaller) {
    $InstallRoot = Join-Path $BuildRoot "installed-smoke"
    $InstalledSmoke = Join-Path $BuildRoot "installed-smoke.png"
    $InstallProcess = Start-Process `
        -FilePath $InstallerPath `
        -ArgumentList @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/DIR=`"$InstallRoot`""
        ) `
        -Wait `
        -PassThru
    if ($InstallProcess.ExitCode -ne 0) {
        throw "The installer smoke test could not install PyCubSim2."
    }
    try {
        $InstalledExe = Join-Path $InstallRoot "PyCubSim2-cli.exe"
        & $InstalledExe --headless --steps 5 --output $InstalledSmoke
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $InstalledSmoke)) {
            throw "The installed PyCubSim2 smoke test failed."
        }
    }
    finally {
        $Uninstaller = Join-Path $InstallRoot "unins000.exe"
        if (Test-Path $Uninstaller) {
            Start-Process `
                -FilePath $Uninstaller `
                -ArgumentList @(
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART"
                ) `
                -Wait | Out-Null
        }
    }
}

$ChecksumLines = @($InstallerPath, $PortableZip) | ForEach-Object {
    $Hash = Get-FileHash -Algorithm SHA256 $_
    "{0}  {1}" -f $Hash.Hash.ToLowerInvariant(), (Split-Path $_ -Leaf)
}
Set-Content -Path $ChecksumPath -Value $ChecksumLines -Encoding Ascii

Write-Host ""
Write-Host "Windows packages:"
Write-Host "  Installer: $InstallerPath"
Write-Host "  Portable:  $PortableZip"
Write-Host "  SHA-256:   $ChecksumPath"
