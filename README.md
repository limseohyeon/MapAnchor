# DWG 지도 업로드

DWG 파일을 브라우저에서 FastAPI로 직접 전송하고 로컬 파일시스템에 저장합니다. 별도 데이터베이스를 사용하지 않습니다.

## 저장 구조

```text
data/drawings/{sha256}/
├─ source/original.dwg
├─ converted/
├─ preview/
└─ metadata.json
```

업로드 파일은 기본 8MB 청크로 저장되며 저장 과정에서 SHA-256을 계산합니다. 애플리케이션 차원의 파일 크기 상한은 없고 디스크의 최소 여유 공간만 확인합니다.

## 사용자 매뉴얼

다른 PC에서 처음 설치·실행하는 방법은 **[docs/사용자_매뉴얼.md](docs/사용자_매뉴얼.md)** 를 따라 하세요.  
Python·ODA File Converter·카카오 API 키 설정, 실행, 문제 해결이 순서대로 정리되어 있습니다.

## 설치 및 실행

```powershell
python -m venv C:\venvs\dwg-map
C:\venvs\dwg-map\Scripts\python.exe -m pip install -r requirements.txt
```

프로젝트 폴더에 `.venv`를 만들어도 됩니다. (`docs/사용자_매뉴얼.md` 참고)

### 더블클릭 실행

프로젝트 루트의 `run_app.bat`을 더블클릭하면 백엔드와 프론트가 함께 뜨고 브라우저가 열립니다.

또는 PowerShell에서:

```powershell
.\scripts\run_app.ps1
```

개별 실행이 필요하면:

```powershell
.\scripts\run_backend.ps1
.\scripts\run_frontend.ps1
```

- API: `http://127.0.0.1:8000`
- API 문서: `http://127.0.0.1:8000/docs`
- Streamlit: `http://localhost:8501`

Python 경로가 다른 경우 `DWG_MAP_PYTHON` 환경 변수에 가상환경의 `python.exe` 경로를 지정합니다.

DWG → DXF 변환에는 PC에 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)가 설치되어 있어야 합니다. 없으면 업로드는 되지만 변환은 `blocked`가 됩니다.

주소 검색에는 카카오 REST API 키가 필요합니다. 프로젝트 폴더의 `.env`에 적어두면 백엔드가 작업 디렉터리 기준 상대경로(`.env`)로 읽어 환경변수로 올립니다. `run_app.ps1`은 프로젝트 루트에서 실행합니다.

1. `.env.example`을 복사해 `.env`를 만들거나, 이미 있는 `.env`를 엽니다.
2. 아래처럼 REST API 키를 넣습니다.

```text
KAKAO_REST_API_KEY=발급받은_REST_API_키
```

3. 백엔드를 다시 시작합니다.

PowerShell에서 직접 넣을 수도 있습니다. 이미 설정된 환경변수가 있으면 `.env` 값보다 우선합니다.

```powershell
$env:KAKAO_REST_API_KEY = "발급받은_REST_API_키"
```

키가 없으면 주소 검색 API는 `address_api_not_configured`로 실패합니다. `.env`는 Git에 올리지 마세요.

## 현재 범위

- DWG/DXF 업로드 검증 및 로컬 저장
- SHA-256 중복 판별, `metadata.json` 원자적 기록
- ODA File Converter를 통한 DWG → DXF 변환(미설치 시 `blocked`)
- 도면 미리보기, 주소 검색, 좌표계 변환, 세션 마커

자세한 설치·사용은 `docs/사용자_매뉴얼.md`를 보세요.
# MapAnchor
