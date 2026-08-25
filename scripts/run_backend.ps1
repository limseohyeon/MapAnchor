$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

$pythonPath = $env:DWG_MAP_PYTHON
if (-not $pythonPath) {
    $pythonPath = Join-Path $env:LOCALAPPDATA 'codex-windspeed-map-venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $fallback = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $fallback) {
        $pythonPath = $fallback
    }
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python 환경을 찾지 못했습니다. DWG_MAP_PYTHON을 설정해 주세요.'
}

$listeners = @(
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
if ($listeners.Count -gt 0) {
    Write-Host '포트 8000이 이미 사용 중입니다.' -ForegroundColor Red
    Write-Host 'run_app.bat 이 켜져 있으면 그 API와 겹칩니다. 둘 중 하나만 실행하세요.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '권장: run_app.bat 만 사용하세요.'
    Write-Host '또는 기존 프로세스를 종료한 뒤 이 스크립트를 다시 실행하세요:'
    foreach ($processId in $listeners) {
        if ($processId -and $processId -gt 0) {
            Write-Host ("  taskkill /PID {0} /T /F" -f $processId)
        }
    }
    exit 1
}

Write-Host "Python: $pythonPath"
Write-Host 'API: http://127.0.0.1:8000'
Write-Host '종료는 Ctrl+C.' -ForegroundColor Cyan
& $pythonPath -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level warning --no-access-log
