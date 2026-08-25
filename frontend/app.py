from __future__ import annotations

import base64
import html
import os
from datetime import timedelta
from typing import Any
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

from frontend.dxf_viewer_html import (
    build_selection_meta_bridge_html,
    build_viewer_shell_html,
)


API_URL = os.getenv("DWG_API_URL", "http://127.0.0.1:8000")
PREPARE_REQUEST_TIMEOUT_SECONDS = int(os.getenv("DWG_PREPARE_REQUEST_TIMEOUT", 120))
ACTIVE_PREPARE_STATUSES = {"preparing"}

st.set_page_config(page_title="DWG 지도", page_icon="🗺️", layout="wide")

# Minimize Streamlit chrome so the drawing viewport dominates the screen.
st.markdown(
    """
<style>
  html, body, [data-testid="stAppViewContainer"] {
    height: 100%;
  }
  [data-testid="stHeader"] {
    height: 0;
    min-height: 0;
    background: transparent;
  }
  [data-testid="stToolbar"] {
    display: none;
  }
  .block-container {
    padding-top: 0.35rem !important;
    padding-bottom: 0.35rem !important;
    padding-left: 0.6rem !important;
    padding-right: 0.6rem !important;
    max-width: 100% !important;
  }
  [data-testid="stVerticalBlock"] {
    gap: 0.35rem !important;
  }
  [data-testid="stHorizontalBlock"] {
    gap: 0.5rem !important;
  }
  [data-testid="stMainBlockContainer"] > div {
    gap: 0.35rem !important;
  }
  div[data-testid="stMarkdownContainer"] p {
    margin-bottom: 1.15rem;
  }
  div[data-testid="stCaptionContainer"] {
    margin-bottom: 0 !important;
  }
  iframe {
    display: block;
  }
  /* Compact list-header buttons; kill markdown p margin that top-aligns label. */
  div[data-testid="stButton"] > button {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    min-height: 0 !important;
    height: auto !important;
    padding: 0.35rem 0.75rem !important;
    line-height: 1.25 !important;
    white-space: nowrap !important;
    font-size: 0.875rem !important;
  }
  div[data-testid="stButton"] > button [data-testid="stMarkdownContainer"],
  div[data-testid="stButton"] > button [data-testid="stMarkdownContainer"] p {
    margin: 0 !important;
    padding: 0 !important;
    line-height: 1.25 !important;
  }
  /* Align Streamlit primary actions with app blue (not default warning-red). */
  button[kind="primary"],
  [data-testid="stBaseButton-primary"],
  [data-testid="baseButton-primary"] {
    background-color: #2563eb !important;
    border-color: #2563eb !important;
  }
  button[kind="primary"]:hover,
  [data-testid="stBaseButton-primary"]:hover,
  [data-testid="baseButton-primary"]:hover {
    background-color: #1d4ed8 !important;
    border-color: #1d4ed8 !important;
  }
  /* Hide fragment sync buttons driven by the drawing-list iframe. */
  [class*="st-key-sel_"],
  [class*="st-key-del_"],
  [class*="st-key-pipeline_refresh"],
  [class*="st-key-logo_tap"] {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
  }
  /* Compact hi-popup X; avoid tall stretched column button. */
  [class*="st-key-hi_popup_x"] {
    display: flex !important;
    justify-content: flex-end !important;
    align-items: flex-start !important;
  }
  [class*="st-key-hi_popup_x"] div[data-testid="stButton"] {
    width: auto !important;
  }
  [class*="st-key-hi_popup_x"] div[data-testid="stButton"] > button {
    min-height: 0 !important;
    height: 1.6rem !important;
    width: 1.6rem !important;
    min-width: 1.6rem !important;
    max-height: 1.6rem !important;
    padding: 0 !important;
    line-height: 1 !important;
    font-size: 0.9rem !important;
  }
</style>
""",
    unsafe_allow_html=True,
)

ACTIVE_CONVERSION_STATUSES = {
    "pending",
    "queued",
    "checking",
    "converting",
    "validating",
}

# Shared visual tokens for Streamlit-adjacent HTML components (Phase B).
UI_FONT = '"Source Sans Pro", "Segoe UI", sans-serif'
UI_TEXT = "#1f2937"
UI_MUTED = "#64748b"
UI_BORDER = "#d1d5db"
UI_SURFACE = "#f8fafc"
UI_PRIMARY = "#2563eb"
UI_SECONDARY = "#334155"
UI_RADIUS = "8px"
UI_DANGER = "#c92a2a"
UI_OK = "#087f5b"

STATUS_COPY: dict[str, tuple[str, str]] = {
    "pending": ("변환 대기 중", "gray"),
    "queued": ("변환 대기 중", "gray"),
    "checking": ("도면 변환 중…", "blue"),
    "converting": ("도면 변환 중…", "blue"),
    "validating": ("도면 변환 중…", "blue"),
    "completed": ("준비됨", "green"),
    "failed": ("변환 실패", "red"),
    "blocked": ("지금은 변환할 수 없음", "orange"),
    "cancelled": ("취소됨", "gray"),
}

STATUS_HINT: dict[str, str] = {
    "pending": "변환 대기 중입니다. 변환이 끝나면 목록이 자동으로 갱신됩니다.",
    "queued": "변환 대기 중입니다. 변환이 끝나면 목록이 자동으로 갱신됩니다.",
    "checking": "파일과 변환 환경을 확인하는 중입니다.",
    "converting": "DXF로 변환하는 중입니다. 잠시만 기다려 주세요.",
    "validating": "변환 결과를 검증하는 중입니다.",
    "blocked": "ODA 설치 또는 디스크 공간을 확인해 주세요.",
    "failed": "변환에 실패했습니다. 아래 원인을 확인하세요.",
}

def drawing_is_view_ready(drawing: dict[str, Any]) -> bool:
    """DXF viewer can open once conversion finished (extents not required)."""
    return str(drawing.get("conversion_status") or "") == "completed"


def drawing_is_address_ready(drawing: dict[str, Any]) -> bool:
    """Address/marker placement requires extents from prepare."""
    if str(drawing.get("conversion_status") or "") != "completed":
        return False
    return (
        drawing.get("extents_min_x") is not None
        and drawing.get("extents_min_y") is not None
        and drawing.get("extents_max_x") is not None
        and drawing.get("extents_max_y") is not None
    )


def drawing_status_copy(drawing: dict[str, Any]) -> tuple[str, str]:
    """List/detail readiness from conversion + extents prepare."""
    conversion = str(drawing.get("conversion_status") or "")
    if conversion != "completed":
        return STATUS_COPY.get(conversion, (conversion or "-", "gray"))

    prepare = str(drawing.get("prepare_status") or "")
    if drawing_is_address_ready(drawing):
        return ("준비됨", "green")
    if prepare == "failed":
        return ("주소 준비 실패", "orange")
    if prepare in ACTIVE_PREPARE_STATUSES:
        return ("주소 준비 중", "blue")
    return ("주소 준비 중", "blue")


def drawing_status_label(drawing: dict[str, Any]) -> str:
    copy, _tone = drawing_status_copy(drawing)
    return copy


def drawing_status_markdown_badge(drawing: dict[str, Any]) -> str:
    copy, tone = drawing_status_copy(drawing)
    return f":{tone}[{copy}]"


def drawing_status_hint(drawing: dict[str, Any]) -> str | None:
    conversion = str(drawing.get("conversion_status") or "")
    if conversion != "completed":
        return STATUS_HINT.get(conversion)
    if drawing_is_address_ready(drawing):
        return None
    prepare = str(drawing.get("prepare_status") or "")
    if prepare == "failed":
        return "주소 검색용 도면 범위 준비에 실패했습니다. 다시 시도를 눌러 주세요."
    return "도면은 표시됩니다. 주소 검색용 범위를 준비하는 중입니다."



def format_size_mb(size_bytes: int | float | None) -> str:
    if size_bytes is None:
        return "-"
    return f"{round(float(size_bytes) / 1048576, 1)} MB"


def clear_drawing_ui_state(drawing_id: str) -> None:
    if st.session_state.get("prepare_drawing_id") == drawing_id:
        st.session_state.pop("prepare_drawing_id", None)
        st.session_state.pop("prepare_info", None)
        st.session_state.pop("prepare_error", None)
    if st.session_state.get("selected_drawing_id") == drawing_id:
        st.session_state.pop("selected_drawing_id", None)
    st.session_state.pop("pending_delete_id", None)


def delete_drawing(drawing_id: str) -> tuple[bool, str]:
    try:
        result = requests.delete(
            f"{API_URL}/api/drawings/{drawing_id}",
            timeout=10,
        )
        if result.status_code >= 400:
            return False, api_error_message(result)
        return True, str(result.json().get("message") or "도면을 삭제했습니다.")
    except requests.RequestException as exc:
        return False, f"삭제 요청에 실패했습니다: {exc}"


@st.dialog("도면 삭제")
def delete_confirm_dialog(drawing: dict) -> None:
    st.warning("삭제 확인 (원본·DXF·미리보기가 모두 제거됩니다)")
    st.markdown(f"**{drawing['original_filename']}**")
    st.caption(
        f'{format_size_mb(drawing.get("size_bytes"))} · '
        f'{drawing_status_label(drawing)}'
    )
    cancel_col, confirm_col = st.columns(2)
    with cancel_col:
        if st.button("취소", use_container_width=True):
            st.session_state.pop("pending_delete_id", None)
            st.rerun()
    with confirm_col:
        if st.button("삭제", use_container_width=True, type="primary"):
            drawing_id = drawing["drawing_id"]
            ok, message = delete_drawing(drawing_id)
            if ok:
                clear_drawing_ui_state(drawing_id)
                st.rerun()
            st.error(message)


def _clear_hi_popup() -> None:
    st.session_state.pop("show_hi_popup", None)


# Display size is 1.5x smaller than the source pixel width (1170 → 780).
_HI_POPUP_IMAGE_WIDTH_PX = 780


@st.dialog(" ", width="large", dismissible=False)
def hi_popup_dialog() -> None:
    # dismissible=False blocks outside-click/ESC dismiss (Streamlit ties those
    # to the native title-bar X). Explicit ✕ + 닫기 both clear and close.
    title_col, x_col = st.columns([20, 1])
    with x_col:
        if st.button("✕", key="hi_popup_x", help="닫기"):
            _clear_hi_popup()
            st.rerun()
    hi_path = Path(__file__).parent / "assets" / "hi.jpg"
    # st.image stays left-aligned in dialogs; center via inline HTML instead.
    encoded = base64.b64encode(hi_path.read_bytes()).decode("ascii")
    st.markdown(
        f'<div style="text-align:center;">'
        f'<img src="data:image/jpeg;base64,{encoded}" '
        f'width="{_HI_POPUP_IMAGE_WIDTH_PX}" '
        f'style="max-width:100%;height:auto;" alt="" />'
        f"</div>",
        unsafe_allow_html=True,
    )
    if st.button("닫기", use_container_width=True, key="hi_popup_close"):
        _clear_hi_popup()
        st.rerun()


def build_header_logo_html(logo_path: Path, *, width_px: int = 150) -> str:
    """Clickable header logo; after 10 clicks, triggers the hidden parent sync button."""
    encoded = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      background: transparent;
      overflow: hidden;
    }}
    img {{
      display: block;
      width: {width_px}px;
      height: auto;
      cursor: pointer;
      user-select: none;
      -webkit-user-drag: none;
    }}
  </style>
</head>
<body>
  <img id="header-logo" src="data:image/png;base64,{encoded}" alt="logo" />
  <script>
    let logoClicks = 0;
    function clickParentLogoEgg() {{
      const buttons = window.parent.document.querySelectorAll("button");
      for (const button of buttons) {{
        if ((button.textContent || "").trim() === "logo-egg") {{
          button.click();
          return true;
        }}
      }}
      return false;
    }}
    document.getElementById("header-logo").addEventListener("click", () => {{
      logoClicks += 1;
      if (logoClicks < 10) return;
      logoClicks = 0;
      clickParentLogoEgg();
    }});
  </script>
</body>
</html>
"""


def _store_prepare_payload(drawing_id: str, payload: dict[str, Any]) -> None:
    st.session_state["prepare_drawing_id"] = drawing_id
    st.session_state["prepare_info"] = payload
    st.session_state["prepare_error"] = None


def request_prepare_async(drawing_id: str, *, force: bool = False) -> dict[str, Any] | None:
    """Queue prepare without blocking the viewer on large DXF files."""
    try:
        response = requests.post(
            f"{API_URL}/api/drawings/{drawing_id}/prepare",
            json={"force": force},
            params={"wait": "false"},
            timeout=15,
        )
        if response.status_code >= 400:
            st.session_state["prepare_drawing_id"] = drawing_id
            st.session_state["prepare_info"] = None
            st.session_state["prepare_error"] = api_error_message(response)
            return None
        payload = response.json()
        _store_prepare_payload(drawing_id, payload)
        return payload
    except requests.RequestException as exc:
        st.session_state["prepare_drawing_id"] = drawing_id
        # Keep viewer usable; prepare can be retried by the poll fragment.
        st.session_state["prepare_error"] = f"도면 준비 요청에 실패했습니다: {exc}"
        return None


def fetch_prepare_info(drawing_id: str) -> dict[str, Any] | None:
    try:
        response = requests.get(
            f"{API_URL}/api/drawings/{drawing_id}/prepare",
            timeout=10,
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
        _store_prepare_payload(drawing_id, payload)
        return payload
    except requests.RequestException:
        return None


def build_upload_component(api_url: str, *, reset_nonce: int = 0) -> str:
    """Upload-only card: dropzone select, confirm, upload with progress."""
    safe_api_url = html.escape(api_url, quote=True)
    return f"""
<!doctype html>
<html lang="ko">
  <head>
  <meta charset="utf-8" />
  <!-- upload-reset:{reset_nonce} -->
  <style>
    body {{
      font-family: {UI_FONT}; margin: 0; color: {UI_TEXT}; font-size: 13px;
    }}
    .card {{
      border: 1px solid {UI_BORDER}; border-radius: {UI_RADIUS};
      padding: 10px; background: #fff;
    }}
    .label {{ font-weight: 600; font-size: 13px; margin-bottom: 6px; }}
    #file {{ display: none; }}
    #dropzone {{
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      gap: 4px; min-height: 72px; padding: 12px 10px; box-sizing: border-box;
      border: 1.5px dashed {UI_BORDER}; border-radius: {UI_RADIUS};
      background: {UI_SURFACE}; cursor: pointer; text-align: center;
      transition: border-color .15s, background .15s;
    }}
    #dropzone:hover, #dropzone:focus-visible {{
      border-color: {UI_PRIMARY}; outline: none;
    }}
    #dropzone.dragover {{
      border-color: {UI_PRIMARY}; background: #eff6ff;
    }}
    #dropzone.has-file {{
      align-items: stretch; text-align: left; cursor: default;
      border-style: solid; background: #fff;
    }}
    #dropzone.disabled {{
      opacity: .6; pointer-events: none;
    }}
    #empty-hint .title {{
      font-size: 13px; font-weight: 600; color: {UI_TEXT};
    }}
    #empty-hint .sub {{
      font-size: 12px; color: {UI_MUTED};
    }}
    #selected-row {{
      display: flex; align-items: center; gap: 6px; min-width: 0;
    }}
    #selected-row[hidden] {{
      display: none !important;
    }}
    #filename {{
      flex: 1; min-width: 0;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      font-size: 13px; font-weight: 600; color: {UI_TEXT};
      line-height: 1.35;
    }}
    #filesize {{
      flex-shrink: 0; font-size: 12px; color: {UI_MUTED}; white-space: nowrap;
    }}
    .actions {{
      display: flex; align-items: center; gap: 8px; margin-top: 8px;
    }}
    button {{
      border: 0; border-radius: 6px; padding: 7px 14px;
      cursor: pointer; font-size: 13px; flex-shrink: 0;
    }}
    button:disabled {{ opacity: .55; cursor: default; }}
    #upload {{
      background: {UI_PRIMARY}; color: white;
    }}
    .icon-btn {{
      display: inline-flex; align-items: center; justify-content: center;
      width: 28px; height: 28px; padding: 0;
      background: #fff; color: {UI_SECONDARY};
      border: 1px solid {UI_BORDER};
    }}
    .icon-btn:hover {{
      border-color: {UI_PRIMARY}; color: {UI_PRIMARY};
    }}
    .icon-btn svg {{
      width: 14px; height: 14px; display: block;
    }}
    #clear:hover {{
      border-color: {UI_DANGER}; color: {UI_DANGER};
    }}
    progress {{ width: 100%; margin-top: 8px; }}
    #status-line {{
      display: block; margin-top: 6px; font-size: 12px; color: {UI_MUTED};
      line-height: 1.35; min-height: 1.35em;
    }}
    #status-line.error {{ color: {UI_DANGER}; }}
    #status-line.ok {{ color: {UI_OK}; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="label">도면 업로드</div>
    <input id="file" type="file" accept=".dwg,.dxf" />
    <div id="dropzone" tabindex="0" role="button" aria-label="DWG 또는 DXF 파일 선택">
      <div id="empty-hint">
        <div class="title">DWG/DXF 파일을 놓거나 클릭해서 선택</div>
        <div class="sub">.dwg · .dxf · 크기 제한 없음</div>
      </div>
      <div id="selected-row" hidden>
        <span id="filename"></span>
        <span id="filesize"></span>
        <button id="change" class="icon-btn" type="button" title="변경" aria-label="파일 변경">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12a9 9 0 1 1-2.6-6.3"/>
            <polyline points="21 3 21 9 15 9"/>
          </svg>
        </button>
        <button id="clear" class="icon-btn" type="button" title="제거" aria-label="선택 제거">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>
    </div>
    <div class="actions">
      <button id="upload" type="button" disabled>업로드 시작</button>
    </div>
    <progress id="progress" value="0" max="100" hidden></progress>
    <span id="status-line"></span>
  </div>
  <script>
    const uploadButton = document.getElementById('upload');
    const changeButton = document.getElementById('change');
    const clearButton = document.getElementById('clear');
    const dropzone = document.getElementById('dropzone');
    const emptyHint = document.getElementById('empty-hint');
    const selectedRow = document.getElementById('selected-row');
    const input = document.getElementById('file');
    const filename = document.getElementById('filename');
    const filesize = document.getElementById('filesize');
    const progress = document.getElementById('progress');
    const statusLine = document.getElementById('status-line');
    const apiUrl = '{safe_api_url}';
    const ACTIVE_CONVERSION = new Set([
      'pending', 'queued', 'checking', 'converting', 'validating'
    ]);
    const CONVERSION_STATUS_LABEL = {{
      pending: '변환 대기 중…',
      queued: '변환 대기 중…',
      checking: '변환 환경 확인 중…',
      converting: 'DXF로 변환 중…',
      validating: '변환 결과 검증 중…',
    }};
    let uploading = false;

    function setStatusLine(text, tone) {{
      statusLine.textContent = text;
      statusLine.className = tone || '';
    }}

    function setBusy(busy) {{
      uploading = busy;
      changeButton.disabled = busy;
      clearButton.disabled = busy;
      dropzone.classList.toggle('disabled', busy);
      if (!busy) syncSelection();
      else uploadButton.disabled = true;
    }}

    function resetUploadForm(statusText, tone) {{
      input.value = '';
      progress.hidden = true;
      progress.value = 0;
      setBusy(false);
      setStatusLine(statusText || '', tone || '');
    }}

    function requestParentRefresh(drawingId) {{
      const buttons = window.parent.document.querySelectorAll('button');
      for (const button of buttons) {{
        const text = (button.textContent || '').trim();
        if (text === 'pipeline:refresh') {{
          button.click();
          return true;
        }}
      }}
      return false;
    }}

    function isDrawingFile(file) {{
      if (!file) return false;
      const name = file.name.toLowerCase();
      return name.endsWith('.dwg') || name.endsWith('.dxf');
    }}

    function formatSize(bytes) {{
      if (!Number.isFinite(bytes)) return '';
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / 1048576).toFixed(1) + ' MB';
    }}

    function assignFile(file) {{
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      setStatusLine('');
      syncSelection();
    }}

    function openPicker() {{
      if (uploading) return;
      input.click();
    }}

    function sleep(ms) {{
      return new Promise((resolve) => setTimeout(resolve, ms));
    }}

    async function waitForConversion(drawingId, initialStatus) {{
      let status = initialStatus || 'pending';
      let lastError = '';
      if (ACTIVE_CONVERSION.has(status)) {{
        setStatusLine(CONVERSION_STATUS_LABEL[status] || '변환을 진행합니다…');
      }}
      while (ACTIVE_CONVERSION.has(status)) {{
        await sleep(2000);
        try {{
          const response = await fetch(
            `${{apiUrl}}/api/drawings/${{encodeURIComponent(drawingId)}}/conversion`
          );
          if (!response.ok) {{
            throw new Error('conversion_status_http');
          }}
          const body = await response.json();
          status = body.conversion_status;
          lastError = body.conversion_error || '';
          if (ACTIVE_CONVERSION.has(status)) {{
            setStatusLine(CONVERSION_STATUS_LABEL[status] || '변환을 진행합니다…');
          }}
        }} catch (_) {{
          resetUploadForm(
            '변환 상태를 확인하지 못했습니다. 목록을 새로고침해 주세요.',
            'error'
          );
          requestParentRefresh(drawingId);
          return;
        }}
      }}
      if (status === 'completed') {{
        const waitedForConversion = ACTIVE_CONVERSION.has(initialStatus || 'pending');
        resetUploadForm(
          waitedForConversion ? '변환이 완료되었습니다.' : '업로드가 완료되었습니다.',
          'ok'
        );
      }} else if (status === 'failed' || status === 'blocked') {{
        resetUploadForm(
          lastError || '변환이 끝났습니다. 목록을 확인해 주세요.',
          'error'
        );
      }} else {{
        resetUploadForm('업로드·변환이 끝났습니다.', 'ok');
      }}
      requestParentRefresh(drawingId);
    }}

    function syncSelection() {{
      const candidate = input.files[0];
      if (candidate && !isDrawingFile(candidate)) {{
        input.value = '';
        setStatusLine('DWG 또는 DXF 파일만 선택할 수 있습니다.', 'error');
      }}
      const file = input.files[0];
      if (file) {{
        emptyHint.hidden = true;
        selectedRow.hidden = false;
        dropzone.classList.add('has-file');
        filename.textContent = file.name;
        filename.title = file.name;
        filesize.textContent = formatSize(file.size);
        uploadButton.disabled = uploading;
      }} else {{
        emptyHint.hidden = false;
        selectedRow.hidden = true;
        dropzone.classList.remove('has-file');
        filename.textContent = '';
        filename.removeAttribute('title');
        filesize.textContent = '';
        uploadButton.disabled = true;
      }}
    }}

    dropzone.addEventListener('click', (event) => {{
      if (event.target.closest('#change') || event.target.closest('#clear')) return;
      if (dropzone.classList.contains('has-file')) return;
      openPicker();
    }});
    dropzone.addEventListener('keydown', (event) => {{
      if (event.key === 'Enter' || event.key === ' ') {{
        event.preventDefault();
        if (!dropzone.classList.contains('has-file')) openPicker();
      }}
    }});
    changeButton.addEventListener('click', (event) => {{
      event.stopPropagation();
      openPicker();
    }});
    clearButton.addEventListener('click', (event) => {{
      event.stopPropagation();
      input.value = '';
      setStatusLine('');
      syncSelection();
    }});

    ;['dragenter', 'dragover'].forEach((type) => {{
      dropzone.addEventListener(type, (event) => {{
        event.preventDefault();
        if (!uploading) dropzone.classList.add('dragover');
      }});
    }});
    ;['dragleave', 'drop'].forEach((type) => {{
      dropzone.addEventListener(type, (event) => {{
        event.preventDefault();
        dropzone.classList.remove('dragover');
      }});
    }});
    dropzone.addEventListener('drop', (event) => {{
      if (uploading) return;
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (!file) return;
      if (!isDrawingFile(file)) {{
        setStatusLine('DWG 또는 DXF 파일만 선택할 수 있습니다.', 'error');
        return;
      }}
      assignFile(file);
    }});

    input.addEventListener('change', () => {{
      if (input.files[0] && isDrawingFile(input.files[0])) {{
        setStatusLine('');
      }}
      syncSelection();
    }});

    uploadButton.addEventListener('click', () => {{
      const file = input.files[0];
      if (!file || !isDrawingFile(file)) {{
        syncSelection();
        return;
      }}

      const form = new FormData();
      form.append('file', file, file.name);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${{apiUrl}}/api/drawings`);
      progress.hidden = false;
      progress.value = 0;
      setBusy(true);
      setStatusLine('업로드 중… 0%');

      xhr.upload.onprogress = (event) => {{
        if (event.lengthComputable) {{
          progress.value = Math.round(event.loaded * 100 / event.total);
        }}
        setStatusLine(`업로드 중… ${{progress.value}}%`);
      }};
      xhr.onload = () => {{
        let body = {{}};
        try {{ body = JSON.parse(xhr.responseText); }} catch (_) {{}}
        if (xhr.status >= 200 && xhr.status < 300) {{
          progress.value = 100;
          const drawingId = body.drawing && body.drawing.drawing_id;
          const conversionStatus = body.drawing && body.drawing.conversion_status;
          if (!drawingId) {{
            resetUploadForm('업로드는 됐지만 도면 ID를 받지 못했습니다.', 'error');
            return;
          }}
          setStatusLine(
            conversionStatus === 'completed'
              ? '업로드했습니다. 목록을 갱신합니다…'
              : '업로드했습니다. 변환이 끝나면 목록을 갱신합니다…',
            'ok'
          );
          waitForConversion(drawingId, conversionStatus);
        }} else {{
          resetUploadForm(body.detail || '업로드에 실패했습니다.', 'error');
        }}
      }};
      xhr.onerror = () => {{
        resetUploadForm('업로드 API에 연결하지 못했습니다.', 'error');
      }};
      xhr.send(form);
    }});
  </script>
</body>
</html>
"""


def build_drawing_list_html(
    drawings: list[dict[str, Any]],
    selected_id: str | None,
    *,
    height_px: int = 560,
    api_url: str | None = None,
) -> str:
    """Drawing table iframe: selects/deletes via hidden Streamlit buttons in the parent."""
    rows: list[str] = []
    for item in drawings:
        drawing_id = str(item["drawing_id"])
        filename = str(item.get("original_filename") or drawing_id)
        conversion_status = str(item.get("conversion_status") or "")
        row_active = conversion_status in ACTIVE_CONVERSION_STATUSES
        is_selected = drawing_id == selected_id
        safe_id = html.escape(drawing_id, quote=True)
        safe_name = html.escape(filename)
        safe_name_attr = html.escape(filename, quote=True)
        safe_status = html.escape(drawing_status_label(item))
        safe_size = html.escape(format_size_mb(item.get("size_bytes")))
        selected_class = " selected" if is_selected else ""
        if row_active:
            delete_cell = (
                '<button type="button" class="delete-btn" disabled '
                'title="변환 중에는 삭제할 수 없습니다.">삭제</button>'
            )
        else:
            delete_cell = (
                f'<button type="button" class="delete-btn" data-action="delete" '
                f'data-id="{safe_id}" title="이 도면을 삭제합니다.">삭제</button>'
            )
        rows.append(
            f"""
      <tr class="row{selected_class}" data-id="{safe_id}" title="{safe_name_attr}">
        <td class="name"><button type="button" class="row-link" data-action="select" data-id="{safe_id}">{safe_name}</button></td>
        <td class="status"><button type="button" class="row-link" data-action="select" data-id="{safe_id}">{safe_status}</button></td>
        <td class="size"><button type="button" class="row-link" data-action="select" data-id="{safe_id}">{safe_size}</button></td>
        <td class="action">{delete_cell}</td>
      </tr>"""
        )

    body = "\n".join(rows) if rows else (
        '<tr class="empty"><td colspan="4">저장된 도면이 없습니다.</td></tr>'
    )
    list_api_url = html.escape((api_url or API_URL).rstrip("/"), quote=True)

    return f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <style>
    html, body {{ margin: 0; padding: 0; overflow: hidden; background: transparent; }}
    .dwg-list-root {{
      height: {height_px}px; box-sizing: border-box;
      border: 1px solid {UI_BORDER}; border-radius: {UI_RADIUS};
      overflow: auto; background: #fff;
      font-family: {UI_FONT}; color: {UI_TEXT}; font-size: 13px;
    }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
    thead th {{
      position: sticky; top: 0; z-index: 1;
      background: {UI_SURFACE}; color: {UI_MUTED};
      font-weight: 600; font-size: 12px; text-align: left;
      padding: 8px 10px; border-bottom: 1px solid {UI_BORDER};
      white-space: nowrap;
    }}
    tbody td {{
      padding: 9px 10px; border-bottom: 1px solid {UI_BORDER};
      vertical-align: middle; line-height: 1.35;
    }}
    tbody tr.row {{ background: #fff; }}
    tbody tr.row:hover {{ background: #f1f5f9; }}
    tbody tr.row.selected {{ background: #e8eef5; }}
    tbody tr.row.selected:hover {{ background: #dde6f0; }}
    tbody tr.row.selected td.name {{ font-weight: 600; }}
    td.name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    td.status, td.size {{
      color: {UI_MUTED}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    td.action {{ text-align: right; white-space: nowrap; }}
    th.name, td.name {{ width: auto; }}
    th.status, td.status {{ width: 5.5rem; }}
    th.size, td.size {{ width: 4.5rem; }}
    th.action, td.action {{ width: 3.6rem; }}
    .row-link {{
      display: block; color: inherit; text-decoration: none;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      cursor: pointer; background: none; border: 0; padding: 0;
      font: inherit; text-align: left; width: 100%;
    }}
    .delete-btn {{
      display: inline-block;
      background: transparent; color: {UI_DANGER}; border: 1px solid {UI_BORDER};
      border-radius: 6px; padding: 3px 8px; font-size: 12px; cursor: pointer;
      text-decoration: none; line-height: 1.2; font-family: inherit;
    }}
    .delete-btn:hover:not(:disabled) {{
      background: #fff5f5; border-color: {UI_DANGER};
    }}
    .delete-btn:disabled {{
      opacity: 0.45; cursor: default; color: {UI_MUTED};
    }}
    tr.empty td {{
      color: {UI_MUTED}; text-align: center; padding: 24px 10px; border-bottom: 0;
    }}
  </style>
</head>
<body>
  <div class="dwg-list-root" id="root">
    <table>
      <thead>
        <tr>
          <th class="name">파일명</th>
          <th class="status">상태</th>
          <th class="size">크기</th>
          <th class="action"></th>
        </tr>
      </thead>
      <tbody id="drawing-list-body">
{body}
      </tbody>
    </table>
  </div>
  <script>
    const apiUrl = "{list_api_url}";
    const activeConversion = new Set([
      "pending", "queued", "checking", "converting", "validating"
    ]);
    const conversionLabels = {{
      pending: "변환 대기 중",
      queued: "변환 대기 중",
      checking: "도면 변환 중…",
      converting: "도면 변환 중…",
      validating: "도면 변환 중…",
      completed: "준비됨",
      failed: "변환 실패",
      blocked: "지금은 변환할 수 없음",
      cancelled: "취소됨",
    }};

    function clickParentSyncButton(kind, drawingId) {{
      const needle = kind + ":" + drawingId;
      const buttons = window.parent.document.querySelectorAll("button");
      for (const button of buttons) {{
        const text = (button.textContent || "").trim();
        if (text === needle) {{
          button.click();
          return true;
        }}
      }}
      return false;
    }}

    function hasExtents(item) {{
      return (
        item
        && item.extents_min_x != null
        && item.extents_min_y != null
        && item.extents_max_x != null
        && item.extents_max_y != null
      );
    }}

    function statusLabel(item) {{
      const conversion = String(item.conversion_status || "");
      if (conversion !== "completed") {{
        return conversionLabels[conversion] || (conversion || "-");
      }}
      if (hasExtents(item)) {{
        return "준비됨";
      }}
      if (String(item.prepare_status || "") === "failed") {{
        return "주소 준비 실패";
      }}
      return "주소 준비 중";
    }}

    function formatSizeMb(sizeBytes) {{
      if (sizeBytes == null || sizeBytes === "") {{
        return "-";
      }}
      return (Number(sizeBytes) / 1048576).toFixed(1) + " MB";
    }}

    function updateDeleteCell(row, item) {{
      const actionCell = row.querySelector("td.action");
      if (!actionCell) {{
        return;
      }}
      const drawingId = String(item.drawing_id || "");
      const converting = activeConversion.has(String(item.conversion_status || ""));
      if (converting) {{
        actionCell.innerHTML =
          '<button type="button" class="delete-btn" disabled ' +
          'title="변환 중에는 삭제할 수 없습니다.">삭제</button>';
        return;
      }}
      actionCell.innerHTML =
        '<button type="button" class="delete-btn" data-action="delete" ' +
        'data-id="' + drawingId.replace(/"/g, "&quot;") + '" ' +
        'title="이 도면을 삭제합니다.">삭제</button>';
    }}

    function applyRemoteStatuses(items) {{
      if (!Array.isArray(items)) {{
        return;
      }}
      const byId = new Map(items.map((item) => [String(item.drawing_id), item]));
      document.querySelectorAll("tr.row[data-id]").forEach((row) => {{
        const drawingId = row.getAttribute("data-id");
        const item = byId.get(drawingId);
        if (!item) {{
          return;
        }}
        const statusBtn = row.querySelector("td.status .row-link");
        if (statusBtn) {{
          statusBtn.textContent = statusLabel(item);
        }}
        const sizeBtn = row.querySelector("td.size .row-link");
        if (sizeBtn) {{
          sizeBtn.textContent = formatSizeMb(item.size_bytes);
        }}
        updateDeleteCell(row, item);
      }});
    }}

    async function refreshListStatuses() {{
      try {{
        const response = await fetch(apiUrl + "/api/drawings");
        if (!response.ok) {{
          return;
        }}
        const items = await response.json();
        applyRemoteStatuses(items);
      }} catch (_) {{
        // Keep the last known labels if the API is briefly unavailable.
      }}
    }}

    document.getElementById("root").addEventListener("click", (event) => {{
      const target = event.target.closest("[data-action]");
      if (!target) return;
      const action = target.getAttribute("data-action");
      const drawingId = target.getAttribute("data-id");
      if (!action || !drawingId) return;
      event.preventDefault();
      if (action === "select") {{
        document.querySelectorAll("tr.row.selected").forEach((row) => {{
          row.classList.remove("selected");
        }});
        const row = document.querySelector(`tr.row[data-id="${{CSS.escape(drawingId)}}"]`);
        if (row) row.classList.add("selected");
        clickParentSyncButton("sel", drawingId);
      }} else if (action === "delete") {{
        clickParentSyncButton("del", drawingId);
      }}
    }});

    refreshListStatuses();
    setInterval(refreshListStatuses, 2000);
  </script>
</body>
</html>
"""


def render_selected_status(selected: dict[str, Any]) -> None:
    """Single status source for the selected drawing (LS-002, LS-005, VW-006)."""
    st.markdown(drawing_status_markdown_badge(selected))
    hint = drawing_status_hint(selected)
    if hint:
        st.caption(hint)
    if selected.get("conversion_error"):
        st.error(selected["conversion_error"])


def _viewer_bundle_url() -> str:
    bundle_path = Path(__file__).resolve().parent / "static" / "dxf-viewer.bundle.js"
    try:
        bundle_version = str(bundle_path.stat().st_mtime_ns)
    except OSError:
        bundle_version = "1"
    return (
        f"{API_URL}/static/dxf-viewer.bundle.js"
        f"?v={html.escape(bundle_version, quote=True)}"
    )


def render_stable_viewer_shell(*, viewer_iframe_height: int = 920) -> None:
    """Emit identical viewer shell HTML so Streamlit can keep the iframe mounted."""
    components.html(
        build_viewer_shell_html(
            viewport_height_px=viewer_iframe_height,
            api_url=API_URL,
            bundle_url=_viewer_bundle_url(),
        ),
        height=viewer_iframe_height,
    )


def bump_viewer_selection_revision(*, force_reload: bool = False) -> None:
    st.session_state["_viewer_selection_revision"] = int(
        st.session_state.get("_viewer_selection_revision") or 0
    ) + 1
    if force_reload:
        st.session_state["_viewer_force_reload"] = True


def render_viewer_selection(
    *,
    api_available: bool,
    drawings: list[dict[str, Any]],
    selected: dict[str, Any] | None,
    selected_id: str | None,
    force_prepare: bool,
) -> None:
    """Update status + parent selection meta. Does not remount the DXF shell."""
    if not api_available:
        st.info("API에 연결되면 도면이 여기에 표시됩니다.")
        components.html(
            build_selection_meta_bridge_html(
                drawing_id="",
                dxf_url="",
                fingerprint="",
                coordinate_system="EPSG:5179",
                coordinate_scale=1000,
                unit_detection=None,
                address_ready=False,
                revision=int(st.session_state.get("_viewer_selection_revision") or 0),
                force_reload=False,
                available_ids=[],
            ),
            height=0,
        )
        return
    if not drawings or selected is None or selected_id is None:
        st.info("변환이 끝난 도면을 선택하면 여기에 표시됩니다.")
        components.html(
            build_selection_meta_bridge_html(
                drawing_id="",
                dxf_url="",
                fingerprint="",
                coordinate_system="EPSG:5179",
                coordinate_scale=1000,
                unit_detection=None,
                address_ready=False,
                revision=int(st.session_state.get("_viewer_selection_revision") or 0),
                force_reload=False,
                available_ids=[],
            ),
            height=0,
        )
        return
    if selected["conversion_status"] != "completed":
        st.info("변환이 끝나면 여기에 표시됩니다.")
        available_ids = [
            str(item["drawing_id"])
            for item in drawings
            if item.get("conversion_status") == "completed"
        ]
        components.html(
            build_selection_meta_bridge_html(
                drawing_id="",
                dxf_url="",
                fingerprint="",
                coordinate_system="EPSG:5179",
                coordinate_scale=1000,
                unit_detection=None,
                address_ready=False,
                revision=int(st.session_state.get("_viewer_selection_revision") or 0),
                force_reload=False,
                available_ids=available_ids,
            ),
            height=0,
        )
        return

    drawing = selected
    prepare_info = st.session_state.get("prepare_info")
    if (
        st.session_state.get("prepare_drawing_id") == selected_id
        and isinstance(prepare_info, dict)
        and isinstance(prepare_info.get("drawing"), dict)
    ):
        drawing = {**selected, **prepare_info["drawing"]}

    needs_prepare = force_prepare or not drawing_is_address_ready(drawing)
    prepare_key = f"_prepare_queued_{selected_id}"
    if needs_prepare and (force_prepare or not st.session_state.get(prepare_key)):
        request_prepare_async(selected_id, force=bool(force_prepare))
        st.session_state[prepare_key] = True
        prepare_info = st.session_state.get("prepare_info")
        if (
            isinstance(prepare_info, dict)
            and isinstance(prepare_info.get("drawing"), dict)
        ):
            drawing = {**selected, **prepare_info["drawing"]}

    if drawing.get("extents_min_x") is not None:
        st.caption(
            "도면 범위: "
            f'({drawing["extents_min_x"]:.1f}, '
            f'{drawing["extents_min_y"]:.1f}) ~ '
            f'({drawing["extents_max_x"]:.1f}, '
            f'{drawing["extents_max_y"]:.1f})'
        )
    elif str(drawing.get("prepare_status") or "") != "failed":
        st.caption("주소 검색용 도면 범위를 준비하는 중입니다.")

    prepare_error = st.session_state.get("prepare_error")
    if prepare_error and st.session_state.get("prepare_drawing_id") == selected_id:
        st.warning(prepare_error)
    if drawing.get("prepare_error"):
        st.warning(f'이전 준비 오류: {drawing["prepare_error"]}')

    available_ids = [
        str(item["drawing_id"])
        for item in drawings
        if item.get("conversion_status") == "completed"
    ]
    force_reload = bool(st.session_state.pop("_viewer_force_reload", False))

    if not drawing_is_view_ready(drawing):
        st.info("도면 표출을 준비하지 못했습니다. 다시 시도를 눌러 주세요.")
        components.html(
            build_selection_meta_bridge_html(
                drawing_id="",
                dxf_url="",
                fingerprint="",
                coordinate_system="EPSG:5179",
                coordinate_scale=1000,
                unit_detection=None,
                address_ready=False,
                revision=int(st.session_state.get("_viewer_selection_revision") or 0),
                force_reload=False,
                available_ids=available_ids,
            ),
            height=0,
        )
        return

    address_ready = drawing_is_address_ready(drawing)
    fingerprint = str(
        drawing.get("prepare_source_hash") or drawing.get("dxf_size_bytes") or "1"
    )
    dxf_url = (
        f"{API_URL}/api/drawings/{selected_id}/dxf"
        f"?v={html.escape(fingerprint, quote=True)}"
    )
    components.html(
        build_selection_meta_bridge_html(
            drawing_id=str(selected_id),
            dxf_url=dxf_url,
            fingerprint=fingerprint,
            coordinate_system=str(drawing.get("coordinate_system") or "EPSG:5179"),
            coordinate_scale=int(drawing.get("coordinate_scale") or 1000),
            unit_detection=(
                str(drawing["unit_detection"])
                if drawing.get("unit_detection") is not None
                else None
            ),
            address_ready=address_ready,
            revision=int(st.session_state.get("_viewer_selection_revision") or 0),
            force_reload=force_reload,
            available_ids=available_ids,
        ),
        height=0,
    )


@st.fragment(run_every=timedelta(seconds=2))
def refresh_when_pipeline_finishes(
    page_statuses: dict[str, tuple[str | None, str | None]],
) -> None:
    """Refresh when conversion readiness changes for list/viewer.

    Prepare-only changes are handled inside the list/viewer iframes so the DXF
    canvas is not remounted and reparsed.
    """
    try:
        response = requests.get(f"{API_URL}/api/drawings", timeout=10)
        response.raise_for_status()
        remote_drawings = response.json()
    except requests.RequestException:
        return

    for item in remote_drawings:
        drawing_id = str(item["drawing_id"])
        remote_conversion = item.get("conversion_status")
        if drawing_id not in page_statuses:
            st.session_state["selected_drawing_id"] = drawing_id
            st.session_state["upload_reset_nonce"] = (
                int(st.session_state.get("upload_reset_nonce") or 0) + 1
            )
            st.rerun()
            return

        page_conversion, _page_prepare = page_statuses[drawing_id]
        if (
            page_conversion in ACTIVE_CONVERSION_STATUSES
            and remote_conversion not in ACTIVE_CONVERSION_STATUSES
        ):
            st.session_state["upload_reset_nonce"] = (
                int(st.session_state.get("upload_reset_nonce") or 0) + 1
            )
            st.rerun()
            return


header_left, header_right = st.columns([6, 1], gap="small")
with header_left:
    logo_path = Path(__file__).parent / "assets" / "header_logo.png"
    # Scaled height for 596x105 logo at width 150 ≈ 26px; keep a small buffer.
    components.html(
        build_header_logo_html(logo_path, width_px=150),
        height=32,
        scrolling=False,
    )
    if st.button("logo-egg", key="logo_tap"):
        st.session_state["show_hi_popup"] = True
        st.rerun()

if st.session_state.get("show_hi_popup"):
    hi_popup_dialog()

# Upload/list iframes may redirect with ?select= or ?delete= after interaction.
select_param = st.query_params.get("select")
if select_param:
    previous = str(st.session_state.get("selected_drawing_id") or "")
    st.session_state["selected_drawing_id"] = select_param
    if previous != str(select_param):
        bump_viewer_selection_revision(force_reload=False)
    try:
        del st.query_params["select"]
    except KeyError:
        pass

delete_param = st.query_params.get("delete")
if delete_param:
    st.session_state["pending_delete_id"] = delete_param
    try:
        del st.query_params["delete"]
    except KeyError:
        pass

drawings: list[dict] = []
api_available = True
try:
    list_response = requests.get(f"{API_URL}/api/drawings", timeout=10)
    list_response.raise_for_status()
    drawings = list_response.json()
except requests.RequestException:
    api_available = False

page_pipeline_statuses = {
    str(item["drawing_id"]): (
        item.get("conversion_status"),
        item.get("prepare_status"),
    )
    for item in drawings
}
# Always poll: a newly uploaded drawing is not on this page until conversion ends.
refresh_when_pipeline_finishes(page_pipeline_statuses)

selected_id: str | None = None
selected: dict | None = None
drawing_by_id: dict[str, dict] = {}

if api_available and drawings:
    drawing_by_id = {item["drawing_id"]: item for item in drawings}
    drawing_ids = [item["drawing_id"] for item in drawings]
    if st.session_state.pop("_select_newest_after_upload", False):
        st.session_state["selected_drawing_id"] = drawing_ids[0]
    saved_id = st.session_state.get("selected_drawing_id")
    if saved_id is None or saved_id not in drawing_by_id:
        st.session_state["selected_drawing_id"] = drawing_ids[0]
    selected_id = st.session_state["selected_drawing_id"]
    selected = drawing_by_id[selected_id]

LIST_VIEWPORT_HEIGHT = 560
VIEWER_IFRAME_HEIGHT = 920

# Upload stays outside the selection fragment so it is not remounted.
# List iframe also stays outside; selection clicks hidden fragment buttons.
# Viewer shell stays outside the fragment and emits identical HTML.
work_col, view_col = st.columns([1.0, 3.6], gap="small")

with view_col:
    viewer_status_host = st.container()
    render_stable_viewer_shell(viewer_iframe_height=VIEWER_IFRAME_HEIGHT)

with work_col:
    components.html(
        build_upload_component(
            API_URL,
            reset_nonce=int(st.session_state.get("upload_reset_nonce") or 0),
        ),
        height=210,
    )
    if st.button("pipeline:refresh", key="pipeline_refresh"):
        st.session_state["upload_reset_nonce"] = (
            int(st.session_state.get("upload_reset_nonce") or 0) + 1
        )
        st.session_state["_select_newest_after_upload"] = True
        st.rerun()

    list_header, refresh_col, regen_col = st.columns([2.0, 0.9, 1.55], gap="small")
    with list_header:
        st.markdown("**내 도면**")
    with refresh_col:
        if st.button("새로고침", use_container_width=True, key="refresh-drawings"):
            st.rerun()
    with regen_col:
        if st.button(
            "다시 표시",
            key="force-prepare",
            type="secondary",
            use_container_width=True,
            disabled=not bool(drawings),
        ):
            current_selected = drawing_by_id.get(
                str(st.session_state.get("selected_drawing_id") or "")
            )
            if (
                current_selected is not None
                and current_selected.get("conversion_status") == "completed"
            ):
                st.session_state["_force_prepare"] = True
                current_id = str(current_selected.get("drawing_id") or "")
                if current_id:
                    st.session_state.pop(f"_prepare_queued_{current_id}", None)
                bump_viewer_selection_revision(force_reload=True)
                st.rerun()

    if not api_available:
        st.warning("업로드 API가 실행 중인지 확인해 주세요.")
    elif not drawings:
        st.info("저장된 도면이 없습니다.")
    else:
        list_drawings = list(drawings)
        prepare_drawing_id = st.session_state.get("prepare_drawing_id")
        prepare_info = st.session_state.get("prepare_info")
        if (
            prepare_drawing_id
            and isinstance(prepare_info, dict)
            and isinstance(prepare_info.get("drawing"), dict)
        ):
            prepared = prepare_info["drawing"]
            list_drawings = [
                {**item, **{
                    key: prepared[key]
                    for key in (
                        "prepare_status",
                        "prepare_error",
                        "prepare_source_hash",
                        "extents_min_x",
                        "extents_min_y",
                        "extents_max_x",
                        "extents_max_y",
                        "coordinate_scale",
                        "drawing_unit",
                        "unit_source",
                        "unit_detection",
                    )
                    if key in prepared
                }}
                if str(item.get("drawing_id")) == str(prepare_drawing_id)
                else item
                for item in list_drawings
            ]
        components.html(
            build_drawing_list_html(
                list_drawings,
                selected_id,
                height_px=LIST_VIEWPORT_HEIGHT,
                api_url=API_URL,
            ),
            height=LIST_VIEWPORT_HEIGHT,
        )

    @st.fragment
    def drawings_viewer_fragment(status_card) -> None:
        """Hidden select/delete sync + selection meta. Viewer shell stays mounted."""
        current_id = st.session_state.get("selected_drawing_id")
        current = drawing_by_id.get(current_id) if current_id else None
        if current is None and drawings:
            current_id = drawings[0]["drawing_id"]
            st.session_state["selected_drawing_id"] = current_id
            current = drawing_by_id[current_id]

        force_prepare = bool(st.session_state.pop("_force_prepare", False))

        for item in drawings:
            drawing_id = str(item["drawing_id"])
            if st.button(
                f"sel:{drawing_id}",
                key=f"sel_{drawing_id}",
                use_container_width=True,
            ):
                previous_id = str(st.session_state.get("selected_drawing_id") or "")
                st.session_state["selected_drawing_id"] = drawing_id
                current_id = drawing_id
                current = drawing_by_id[drawing_id]
                if previous_id != drawing_id:
                    bump_viewer_selection_revision(force_reload=False)
            if item.get("conversion_status") not in ACTIVE_CONVERSION_STATUSES:
                if st.button(
                    f"del:{drawing_id}",
                    key=f"del_{drawing_id}",
                    use_container_width=True,
                ):
                    st.session_state["pending_delete_id"] = drawing_id
                    st.rerun()

        pending_delete_id = st.session_state.get("pending_delete_id")
        if pending_delete_id and pending_delete_id in drawing_by_id:
            delete_confirm_dialog(drawing_by_id[pending_delete_id])
        elif pending_delete_id:
            st.session_state.pop("pending_delete_id", None)

        box = status_card.empty()
        with box:
            if api_available and drawings and current is not None:
                status_drawing = current
                prepare_info = st.session_state.get("prepare_info")
                if (
                    st.session_state.get("prepare_drawing_id") == current_id
                    and isinstance(prepare_info, dict)
                    and isinstance(prepare_info.get("drawing"), dict)
                ):
                    status_drawing = {**current, **prepare_info["drawing"]}
                render_selected_status(status_drawing)
            render_viewer_selection(
                api_available=api_available,
                drawings=drawings,
                selected=current,
                selected_id=current_id,
                force_prepare=force_prepare,
            )

    drawings_viewer_fragment(viewer_status_host)
