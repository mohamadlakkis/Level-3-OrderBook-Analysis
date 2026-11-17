# Run in Windows PowerShell, from the repository root.
# Command: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows_setup.ps1
param([string]$Url = "https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/12302019.NASDAQ_ITCH50.gz")
$ErrorActionPreference = "Stop"

$rawDirectory = Join-Path $PSScriptRoot "data\raw"
New-Item -ItemType Directory -Path $rawDirectory -Force | Out-Null
$destination = Join-Path $rawDirectory "12302019.NASDAQ_ITCH50.gz"

curl.exe --fail --location --retry 3 --continue-at - --output $destination $Url
exit $LASTEXITCODE
