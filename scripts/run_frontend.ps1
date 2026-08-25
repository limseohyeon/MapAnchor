$pythonPath = $env:DWG_MAP_PYTHON
if (-not $pythonPath) {
    $pythonPath = Join-Path $env:LOCALAPPDATA 'codex-windspeed-map-venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python 환경을 찾지 못했습니다. DWG_MAP_PYTHON을 설정해 주세요.'
}
& $pythonPath -m streamlit run frontend/app.py

