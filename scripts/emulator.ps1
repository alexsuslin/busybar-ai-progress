[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("install", "start")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$emulatorRoot = Join-Path $projectRoot ".dev\busybar-emulator"
$webRoot = Join-Path $emulatorRoot "web"

function Resolve-Tool {
    param(
        [Parameter(Mandatory)]
        [string]$Name,
        [Parameter(Mandatory)]
        [string]$Fallback
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    if (Test-Path -LiteralPath $Fallback) {
        return $Fallback
    }
    throw "Required tool '$Name' was not found."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [string]$Program,
        [Parameter(ValueFromRemainingArguments)]
        [string[]]$Arguments
    )

    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Program"
    }
}

$node = Resolve-Tool -Name "node.exe" -Fallback "C:\Program Files\nodejs\node.exe"
$npm = Resolve-Tool -Name "npm.cmd" -Fallback "C:\Program Files\nodejs\npm.cmd"

if ($Action -eq "install") {
    $git = Resolve-Tool -Name "git.exe" -Fallback "C:\Program Files\Git\cmd\git.exe"
    if (-not (Test-Path -LiteralPath $emulatorRoot)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $emulatorRoot) -Force | Out-Null
        Invoke-Checked $git clone --depth 1 https://github.com/maxswinkels/busybar-emulator.git $emulatorRoot
    }
    elseif (-not (Test-Path -LiteralPath (Join-Path $emulatorRoot ".git"))) {
        throw "Refusing to reuse '$emulatorRoot' because it is not a Git checkout."
    }

    Push-Location $webRoot
    try {
        Invoke-Checked $npm install
        Invoke-Checked $npm run build
    }
    finally {
        Pop-Location
    }

    Write-Host "BUSY Bar emulator installed in $emulatorRoot"
    exit 0
}

$serverPath = Join-Path $emulatorRoot "server.js"
if (-not (Test-Path -LiteralPath $serverPath)) {
    throw "Emulator is not installed. Run: .\scripts\emulator.ps1 install"
}

Write-Host "Starting BUSY Bar emulator at http://127.0.0.1:8080"
Push-Location $emulatorRoot
try {
    Invoke-Checked $node server.js
}
finally {
    Pop-Location
}
