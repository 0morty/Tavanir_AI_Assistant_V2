# PowerShell runner for Tavanir AI Assistant V2 in Decoupled Mock Mode
$env:IS_MOCK = "true"
Write-Host "[*] Starting Tavanir AI Assistant V2 in MOCK mode..." -ForegroundColor Cyan
Write-Host "[*] Interactive Documentation: http://localhost:8000/scalar" -ForegroundColor Green
Write-Host "[*] Default Header: X-API-Key: tavanir_default_secret_api_key_2026" -ForegroundColor Yellow
uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload
