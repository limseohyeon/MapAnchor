# MapAnchor

> CAD 도면(DWG/DXF)을 브라우저에서 열고, **주소로 위치를 찍어** 도면 좌표에 연결하는 로컬 웹 앱

데이터베이스 없이 로컬 파일만 사용합니다. Windows PC에서 실행하는 것을 기준으로 합니다.

---

## 무엇을 하나요?

```text
도면 업로드  →  DXF 변환·표시  →  주소 검색  →  도면 위 마커
```

| 단계 | 설명 |
|:----:|------|
| 1️⃣ | `.dwg` / `.dxf` 업로드 |
| 2️⃣ | 브라우저에서 도면 열람 (줌·좌표계·단위) |
| 3️⃣ | 카카오 주소 검색 → 도면 좌표로 변환 |
| 4️⃣ | 도면 범위 안이면 세션 마커 표시 |

---

## 주요 기능

| | 기능 | 비고 |
|---|------|------|
| 📂 | 도면 업로드·목록·삭제 | SHA-256 중복 판별 |
| 🔄 | DWG → DXF 자동 변환 | [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) 필요 |
| 🗺️ | 브라우저 DXF 뷰어 | Three.js / dxf-viewer |
| 📍 | 주소 → 도면 마커 | 카카오 Local API |
| 🧭 | 한국 좌표계 | `EPSG:5179` 등 Korea 2000 계열 |
| 📏 | 도면 단위 | m(×1) / mm(×1000), 자동·수동 |

---

## 구성

```text
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│  Streamlit  │────▶│   FastAPI   │────▶│  로컬 저장소  │
│  :8501      │     │   :8000     │     │  data/…      │
└─────────────┘     └─────────────┘     └──────────────┘
                           │
                    ┌──────┴──────┐
                    │ ODA / 카카오 │
                    └─────────────┘
```

| 경로 | 역할 |
|------|------|
| `frontend/` | UI · DXF 뷰어 |
| `backend/` | 업로드 · 변환 · 좌표 · 주소 API |
| `data/drawings/` | 도면·메타데이터 (DB 대체) |
| `docs/` | 설치·사용 매뉴얼 |

**저장 구조**

```text
data/drawings/{sha256}/
├─ source/original.dwg
├─ converted/
├─ preview/
└─ metadata.json
```

---

## 빠른 시작

> 처음 설치·카카오 키·ODA 설정은 **[사용자 매뉴얼](docs/사용자_매뉴얼.md)** 을 따르세요.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`.env.example` → `.env` 복사 후 키 설정:

```text
KAKAO_REST_API_KEY=발급받은_REST_API_키
```

실행:

```text
run_app.bat          # 더블클릭
# 또는
.\scripts\run_app.ps1
```

| | URL |
|---|-----|
| 🖥️ UI | http://localhost:8501 |
| 🔌 API | http://127.0.0.1:8000 |
| 📘 Docs | http://127.0.0.1:8000/docs |

---

## 알아두면 좋은 점

- ☁️ 클라우드·멀티유저·인증 없음 — **로컬 전용**
- 💾 마커는 **세션 한정** (영구 저장하지 않음)
- 🧱 DWG는 ODA 미설치 시 변환이 `blocked`
- 🔑 주소 검색은 카카오 REST API 키 필요 (`.env`는 Git에 올리지 마세요)

자세한 문제 해결은 [사용자 매뉴얼](docs/사용자_매뉴얼.md)을 참고하세요.

---

## 📜 라이선스

Copyright © 2026 seohyeon. All Rights Reserved.

본 저장소의 소스코드는 **열람(공개) 목적**으로 제공됩니다.  
저작권자의 **사전 서면 허가 없이** 아래 행위를 금합니다.

- 복제, 수정, 배포
- 상업적·비상업적 이용
- 2차 저작물(파생작) 제작
- Fork 후 재배포

문의·사용 허가가 필요하면 저장소 소유자에게 직접 연락하세요.
