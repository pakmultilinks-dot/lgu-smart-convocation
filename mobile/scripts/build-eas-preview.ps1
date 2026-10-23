# One-command EAS APK builder for a user who is authorized on the existing
# Expo project. No passwords, tokens, app secrets or release keys are written.
$ErrorActionPreference = "Stop"
$project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $project
try {
  Write-Host "LGU Convocation Preview - Expo EAS Android APK" -ForegroundColor Cyan
  Write-Host "This command requires an Expo account with access to the configured project."
  Write-Host "Expo Free plan may place cloud builds in a queue."
  & npx eas-cli@latest whoami
  if ($LASTEXITCODE -ne 0) {
    & npx eas-cli@latest login
    if ($LASTEXITCODE -ne 0) { throw "Expo login was not completed." }
  }
  & npx eas-cli@latest build --platform android --profile preview --message "LGU synthetic QA preview APK"
  if ($LASTEXITCODE -ne 0) {
    throw "EAS build did not start/finish. Check project access (app.json owner) and the Expo build log."
  }
  Write-Host "Your Expo EAS build page link is shown in the output above."
} finally {
  Pop-Location
}
