param(
    [int]$Port = 0
)

# PowerShell runner for Tavanir AI Assistant V2 in Decoupled Mock Mode
if (Test-Path "$PSScriptRoot\..\.venv\Scripts\Activate.ps1") {
    . "$PSScriptRoot\..\.venv\Scripts\Activate.ps1"
}

if ($Port -le 0) {
    $inputPort = Read-Host "Enter port to run the mock server [default: 8000]"
    if ([string]::IsNullOrWhiteSpace($inputPort)) {
        $Port = 8000
    } else {
        $Port = [int]$inputPort
    }
}

$env:PYTHONPATH = "."
$env:IS_MOCK = "true"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "[*] Starting Tavanir AI Assistant V2 in MOCK mode via FastAPI CLI on port $Port..." -ForegroundColor Cyan
Write-Host "[*] Interactive Documentation: http://localhost:$Port/scalar" -ForegroundColor Green
Write-Host "[*] Default Header: X-API-Key: tavanir_default_secret_api_key_2026" -ForegroundColor Yellow

fastapi dev src/presentation/mock_server.py --host 0.0.0.0 --port $Port


