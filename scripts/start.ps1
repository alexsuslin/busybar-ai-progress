[CmdletBinding()]
param([switch]$NoInput, [switch]$Doctor, [switch]$Help)

$ErrorActionPreference = 'Stop'
$projectRoot = (Split-Path -Parent $PSScriptRoot).Replace('\', '/')
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is not installed. Follow README.md first.'
}
$uvArguments = @('run', '--no-sync', '--project', $projectRoot)
$envFile = (Join-Path $projectRoot '.env').Replace('\', '/')
if (Test-Path -LiteralPath $envFile) {
    $uvArguments += @('--env-file', $envFile)
}
$uvArguments += 'busybar-codex'
if ($Help) { $uvArguments += '--help' }
elseif ($Doctor) { $uvArguments += 'doctor' }
else {
    $uvArguments += 'run'
    if ($NoInput) { $uvArguments += '--no-input' }
}
Push-Location $projectRoot
try {
    & uv @uvArguments
    exit $LASTEXITCODE
}
finally { Pop-Location }
