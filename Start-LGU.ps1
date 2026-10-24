# Run this checkout, regardless of the terminal's current directory.
$ErrorActionPreference = 'Stop'
$mobileDirectory = Join-Path $PSScriptRoot 'mobile'
if (-not (Test-Path -LiteralPath (Join-Path $mobileDirectory 'node_modules/expo/bin/cli'))) {
    throw 'Install mobile dependencies first: cd mobile; npm ci'
}
Write-Host "Starting LGU Convocation from $PSScriptRoot"
Push-Location -LiteralPath $mobileDirectory
try {
    & npm start @args
    if ($LASTEXITCODE -ne 0) { throw "LGU startup exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
