from __future__ import annotations

import html

from backend.crs import COORDINATE_SYSTEM_LABELS, COORDINATE_SYSTEM_OPTIONS


UI_FONT = '"Source Sans Pro", "Segoe UI", sans-serif'
UI_TEXT = "#1f2937"
UI_MUTED = "#64748b"
UI_BORDER = "#d1d5db"
UI_SURFACE = "#f8fafc"
UI_PRIMARY = "#2563eb"
UI_RADIUS = "8px"
UI_DANGER = "#c92a2a"
UI_OK = "#087f5b"

# Keep at most the current drawing and two recent ones parsed in-memory.
VIEWER_SLOT_LIMIT = 3
SELECTION_META_ID = "dwg-viewer-selection-meta"


def build_viewer_shell_html(
    *,
    viewport_height_px: int,
    api_url: str,
    bundle_url: str,
) -> str:
    """Stable DXF viewer shell. Selection comes from parent DOM meta, not srcdoc."""
    safe_api_url = html.escape(api_url.rstrip("/"), quote=True)
    safe_bundle_url = html.escape(bundle_url, quote=True)
    safe_meta_id = html.escape(SELECTION_META_ID, quote=True)
    crs_options_html = "".join(
        (
            "<option value=\""
            f"{html.escape(code, quote=True)}\">"
            f"{html.escape(COORDINATE_SYSTEM_LABELS.get(code, code))}"
            "</option>"
        )
        for code in COORDINATE_SYSTEM_OPTIONS
    )
    viewport_css_height = max(320, int(viewport_height_px) - 56)
    slot_limit = int(VIEWER_SLOT_LIMIT)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <style>
    html, body {{
      margin: 0; padding: 0; height: 100%;
      font-family: {UI_FONT}; color: {UI_TEXT}; background: #fff;
    }}
    .shell {{
      display: flex; flex-direction: column; height: 100%;
      box-sizing: border-box;
    }}
    .toolbar {{
      display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
      padding: 8px 10px; border-bottom: 1px solid {UI_BORDER};
      background: {UI_SURFACE}; box-sizing: border-box;
    }}
    .toolbar-zoom, .toolbar-address {{
      display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
    }}
    .toolbar button {{
      border: 1px solid {UI_BORDER}; background: #fff; color: {UI_TEXT};
      border-radius: 6px; padding: 6px 10px; font-size: 13px; cursor: pointer;
    }}
    .toolbar button:hover {{ background: #eff6ff; border-color: {UI_PRIMARY}; }}
    .toolbar select, .toolbar input {{
      border: 1px solid {UI_BORDER}; border-radius: 6px; padding: 6px 8px;
      font-size: 13px; font-family: inherit; background: #fff; color: {UI_TEXT};
    }}
    .address-search-box {{ position: relative; min-width: 220px; flex: 1 1 220px; }}
    #address-query {{ width: 100%; box-sizing: border-box; }}
    #address-dropdown {{
      position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 40;
      max-height: 280px; max-width: 420px; overflow: auto;
      background: #fff; border: 1px solid {UI_BORDER}; border-radius: 6px;
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.12);
    }}
    #address-dropdown[hidden] {{ display: none !important; }}
    #address-results-list {{ list-style: none; margin: 0; padding: 0; }}
    .address-result-item {{
      display: block; width: 100%; box-sizing: border-box;
      padding: 9px 12px; border: 0; border-bottom: 1px solid {UI_BORDER};
      background: #fff; color: {UI_TEXT}; text-align: left; cursor: pointer;
      font-family: inherit; font-size: 13px; border-radius: 0;
    }}
    .address-result-item:last-child {{ border-bottom: 0; }}
    .address-result-item:hover,
    .address-result-item.active {{ background: #eff6ff; }}
    .address-result-title {{
      display: block; font-size: 13px; font-weight: 600; line-height: 1.35;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .address-result-subtitle {{
      display: block; margin-top: 2px; font-size: 12px; color: {UI_MUTED}; line-height: 1.35;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .address-result-title mark,
    .address-result-subtitle mark {{
      background: rgba(37, 99, 235, 0.18); color: inherit; padding: 0; border-radius: 2px;
    }}
    .address-dropdown-empty {{
      padding: 10px; font-size: 13px; color: {UI_MUTED}; line-height: 1.4;
    }}
    #address-dropdown-empty[hidden] {{ display: none !important; }}
    #zoom-level {{ font-size: 12px; color: {UI_MUTED}; min-width: 4.5em; }}
    #hint {{ font-size: 12px; color: {UI_MUTED}; }}
    #address-status {{
      flex: 0 0 100%; font-size: 12px; color: {UI_MUTED}; min-height: 1.2em;
      line-height: 1.3;
    }}
    #address-status.error {{ color: {UI_DANGER}; }}
    #address-status.ok {{ color: {UI_OK}; }}
    #viewport {{
      width: 100%; height: {viewport_css_height}px; flex: 1 1 auto;
      overflow: hidden; position: relative;
      border: 1px solid {UI_BORDER}; border-radius: {UI_RADIUS}; background: {UI_SURFACE};
    }}
    #slot-root {{
      position: absolute; inset: 0; overflow: hidden;
    }}
    .viewer-slot {{
      position: absolute; inset: 0; overflow: hidden;
      visibility: hidden; pointer-events: none;
    }}
    .viewer-slot.active {{
      visibility: visible; pointer-events: auto;
    }}
    .viewer-slot canvas {{
      display: block; width: 100% !important; height: 100% !important;
    }}
    #load-status {{
      position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
      background: rgba(248, 250, 252, 0.92); color: {UI_MUTED}; font-size: 14px; z-index: 5;
    }}
    #load-status[hidden] {{ display: none !important; }}
    #marker-layer {{
      position: absolute; left: 0; top: 0; right: 0; bottom: 0;
      pointer-events: none; overflow: hidden; z-index: 2;
    }}
    .marker {{
      position: absolute; left: 0; top: 0;
      transform: translate(-50%, -100%);
      z-index: 2; pointer-events: auto; cursor: pointer;
    }}
    .marker .pin {{
      width: 16px; height: 16px;
      background: {UI_DANGER}; border: 2px solid #fff;
      border-radius: 50% 50% 50% 0; transform: rotate(-45deg);
      box-shadow: 0 1px 3px rgba(0,0,0,.35);
    }}
    .marker.probe .pin {{ background: {UI_PRIMARY}; }}
    .marker .label {{
      position: absolute; left: 18px; top: -2px;
      max-width: 220px; padding: 2px 6px;
      background: rgba(255,255,255,.94); color: {UI_TEXT};
      border: 1px solid {UI_BORDER}; border-radius: 4px;
      font-size: 12px; line-height: 1.3; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
      box-shadow: 0 1px 2px rgba(0,0,0,.12);
    }}
    #marker-context-menu {{
      position: absolute; z-index: 50; min-width: 72px;
      background: #fff; border: 1px solid {UI_BORDER}; border-radius: 6px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.14); overflow: hidden;
    }}
    #marker-context-menu[hidden] {{ display: none !important; }}
    #marker-context-menu button {{
      display: block; width: 100%; box-sizing: border-box;
      padding: 8px 12px; border: 0; border-radius: 0;
      background: #fff; color: {UI_DANGER}; text-align: left;
      font-family: inherit; font-size: 13px; cursor: pointer;
    }}
    #marker-context-menu button:hover {{ background: #fef2f2; }}
  </style>
  <script src="{safe_bundle_url}"></script>
</head>
<body>
  <div class="shell">
  <div class="toolbar">
    <div class="toolbar-zoom">
      <button id="zoom-in" type="button">확대</button>
      <button id="zoom-out" type="button">축소</button>
      <button id="fit" type="button">전체 보기</button>
      <span id="zoom-level">100%</span>
      <span id="hint">드래그로 이동 · 휠로 확대/축소 · 더블클릭으로 좌표 확인</span>
    </div>
    <div class="toolbar-address">
      <select id="coordinate-system" aria-label="도면 좌표계">{crs_options_html}</select>
      <select id="coordinate-scale" aria-label="도면 단위">
        <option value="1000" selected>밀리미터 (×1000)</option>
        <option value="1">미터 (×1)</option>
      </select>
      <div class="address-search-box" id="address-search-box">
        <input id="address-query" type="text" placeholder="도로명 또는 지번 주소" autocomplete="off" aria-autocomplete="list" aria-controls="address-dropdown" aria-expanded="false" />
        <div id="address-dropdown" hidden role="listbox" aria-label="검색 결과">
          <div id="address-dropdown-empty" class="address-dropdown-empty" hidden>검색 결과가 없습니다.</div>
          <ul id="address-results-list"></ul>
        </div>
      </div>
      <button id="address-search" type="button">검색</button>
    </div>
    <div id="address-status"></div>
  </div>
  <div id="viewport">
    <div id="slot-root"></div>
    <div id="load-status">도면을 선택하면 여기에 표시됩니다.</div>
    <div id="marker-layer"></div>
    <div id="marker-context-menu" hidden>
      <button id="marker-delete-btn" type="button">삭제</button>
    </div>
  </div>
  </div>
  <script>
    const VIEWER_SLOT_LIMIT = {slot_limit};
    const SELECTION_META_ID = '{safe_meta_id}';
    const viewport = document.getElementById('viewport');
    const slotRoot = document.getElementById('slot-root');
    const loadStatus = document.getElementById('load-status');
    const zoomLevel = document.getElementById('zoom-level');
    const addressQuery = document.getElementById('address-query');
    const addressSearch = document.getElementById('address-search');
    const addressSearchBox = document.getElementById('address-search-box');
    const addressDropdown = document.getElementById('address-dropdown');
    const addressDropdownEmpty = document.getElementById('address-dropdown-empty');
    const addressResultsList = document.getElementById('address-results-list');
    const addressStatus = document.getElementById('address-status');
    const coordinateSystem = document.getElementById('coordinate-system');
    const coordinateScale = document.getElementById('coordinate-scale');
    const markerLayer = document.getElementById('marker-layer');
    const markerContextMenu = document.getElementById('marker-context-menu');
    const markerDeleteBtn = document.getElementById('marker-delete-btn');
    const apiUrl = '{safe_api_url}';

    const slots = new Map();
    let activeKey = null;
    let activeSlot = null;
    let lastSelectionSig = '';
    let lastAppliedRevision = '';
    let metaPollTimer = null;

    let viewer = null;
    let viewerReady = false;
    let drawingId = '';
    let unitDetection = '';
    let addressReady = false;
    let preparePollTimer = null;
    let currentCoordinateScale = 1000;
    let currentCoordinateSystem = 'EPSG:5179';
    let baseViewWidth = null;
    let lastPointerScene = null;

    let savingCoordinateSettings = false;
    let addressItems = [];
    let selectedAddress = null;
    let markers = [];
    let markerSeq = 0;
    let contextMenuMarkerId = null;
    let addressActiveIndex = -1;
    let addressShowEmpty = false;
    let addressHighlightQuery = '';

    function setLoadStatus(text) {{
      if (!text) {{
        loadStatus.hidden = true;
        loadStatus.textContent = '';
        return;
      }}
      loadStatus.hidden = false;
      loadStatus.textContent = text;
    }}

    function slotKey(drawingIdValue, fingerprint) {{
      return String(drawingIdValue || '') + '@' + String(fingerprint || '');
    }}

    function touchSlot(slot) {{
      slot.touchedAt = Date.now();
    }}

    function stopPreparePolling() {{
      if (preparePollTimer != null) {{
        clearInterval(preparePollTimer);
        preparePollTimer = null;
      }}
    }}

    function nextMarkerId() {{
      markerSeq += 1;
      if (window.crypto && typeof window.crypto.randomUUID === 'function') {{
        return window.crypto.randomUUID();
      }}
      return 'marker-' + markerSeq;
    }}

    function hideContextMenu() {{
      contextMenuMarkerId = null;
      markerContextMenu.hidden = true;
    }}

    function showContextMenu(markerId, clientX, clientY) {{
      contextMenuMarkerId = markerId;
      const rect = viewport.getBoundingClientRect();
      let left = clientX - rect.left;
      let top = clientY - rect.top;
      markerContextMenu.hidden = false;
      const menuWidth = markerContextMenu.offsetWidth || 72;
      const menuHeight = markerContextMenu.offsetHeight || 36;
      left = Math.min(Math.max(0, left), Math.max(0, rect.width - menuWidth));
      top = Math.min(Math.max(0, top), Math.max(0, rect.height - menuHeight));
      markerContextMenu.style.left = left + 'px';
      markerContextMenu.style.top = top + 'px';
    }}

    function removeMarker(markerId) {{
      markers = markers.filter((item) => item.id !== markerId);
      renderMarkers();
      hideContextMenu();
    }}

    function clearMarkers() {{
      markers = [];
      renderMarkers();
      hideContextMenu();
    }}

    function drawingToScene(xMm, yMm) {{
      if (!viewer || !viewer.GetOrigin) {{
        return null;
      }}
      const origin = viewer.GetOrigin();
      return {{
        x: Number(xMm) - Number(origin.x || 0),
        y: Number(yMm) - Number(origin.y || 0),
      }};
    }}

    function sceneToDrawing(sceneX, sceneY) {{
      if (!viewer || !viewer.GetOrigin) {{
        return null;
      }}
      const origin = viewer.GetOrigin();
      return {{
        x_mm: Number(sceneX) + Number(origin.x || 0),
        y_mm: Number(sceneY) + Number(origin.y || 0),
      }};
    }}

    function sceneToScreen(sceneX, sceneY) {{
      if (!viewer || !window.THREE) {{
        return null;
      }}
      const camera = viewer.GetCamera();
      const canvas = viewer.GetCanvas();
      if (!camera || !canvas) {{
        return null;
      }}
      const vector = new window.THREE.Vector3(sceneX, sceneY, 0);
      vector.project(camera);
      const width = canvas.clientWidth || canvas.width;
      const height = canvas.clientHeight || canvas.height;
      return {{
        x: (vector.x * 0.5 + 0.5) * width,
        y: (-vector.y * 0.5 + 0.5) * height,
      }};
    }}

    function updateZoomLabel() {{
      if (!viewer || !viewer.GetCamera || baseViewWidth == null) {{
        zoomLevel.textContent = '—';
        return;
      }}
      const cam = viewer.GetCamera();
      const width = Math.abs(cam.right - cam.left);
      const percent = Math.round((baseViewWidth / Math.max(width, 1e-9)) * 100);
      zoomLevel.textContent = percent + '%';
    }}

    function updateMarkerScreenPositions() {{
      const nodes = markerLayer.querySelectorAll('.marker');
      nodes.forEach((el) => {{
        const item = markers.find((m) => m.id === el.dataset.markerId);
        if (!item || item.x_mm == null || item.y_mm == null) {{
          el.style.display = 'none';
          return;
        }}
        const scene = drawingToScene(item.x_mm, item.y_mm);
        const screen = scene ? sceneToScreen(scene.x, scene.y) : null;
        if (!screen) {{
          el.style.display = 'none';
          return;
        }}
        el.style.display = '';
        el.style.left = screen.x + 'px';
        el.style.top = screen.y + 'px';
      }});
    }}

    function renderMarkers() {{
      markerLayer.innerHTML = '';
      markers.forEach((item) => {{
        const el = document.createElement('div');
        el.className = item.kind === 'probe' ? 'marker probe' : 'marker';
        el.dataset.markerId = item.id;
        el.setAttribute('role', 'img');
        el.setAttribute('aria-label', item.display_name || '선택 위치');
        const pin = document.createElement('div');
        pin.className = 'pin';
        pin.setAttribute('aria-hidden', 'true');
        const label = document.createElement('div');
        label.className = 'label';
        label.textContent = item.display_name || '선택 위치';
        label.title = label.textContent;
        el.appendChild(pin);
        el.appendChild(label);
        el.addEventListener('contextmenu', (event) => {{
          event.preventDefault();
          event.stopPropagation();
          showContextMenu(item.id, event.clientX, event.clientY);
        }});
        el.addEventListener('pointerdown', (event) => {{
          event.stopPropagation();
        }});
        markerLayer.appendChild(el);
      }});
      updateMarkerScreenPositions();
    }}

    function focusOnMarker(item) {{
      if (!viewer || !item || item.x_mm == null || item.y_mm == null) {{
        return;
      }}
      const scene = drawingToScene(item.x_mm, item.y_mm);
      if (!scene) {{
        return;
      }}
      const cam = viewer.GetCamera();
      const currentWidth = Math.abs(cam.right - cam.left);
      const nextWidth = Math.min(currentWidth, Math.max(currentWidth / 4, 50));
      viewer.SetView({{ x: scene.x, y: scene.y }}, nextWidth);
      viewer.Render();
      updateZoomLabel();
      updateMarkerScreenPositions();
    }}

    function addMarker(coordinate, label) {{
      const item = {{
        id: nextMarkerId(),
        kind: 'address',
        x_mm: coordinate.x_mm,
        y_mm: coordinate.y_mm,
        display_name: label || coordinate.display_name || '선택 위치',
      }};
      markers.push(item);
      renderMarkers();
      focusOnMarker(item);
    }}

    function formatProbeLabel(coordinate) {{
      const x = Number(coordinate.x_mm);
      const y = Number(coordinate.y_mm);
      return `X ${{x.toFixed(1)}}, Y ${{y.toFixed(1)}}`;
    }}

    function addProbeMarker(coordinate) {{
      const item = {{
        id: nextMarkerId(),
        kind: 'probe',
        x_mm: coordinate.x_mm,
        y_mm: coordinate.y_mm,
        display_name: formatProbeLabel(coordinate),
      }};
      markers.push(item);
      renderMarkers();
    }}

    async function probeCoordinatesAt(xMm, yMm) {{
      if (!addressReady || !drawingId) {{
        setAddressStatus('도면 범위 준비 중… 좌표 확인을 아직 사용할 수 없습니다.', 'error');
        return;
      }}
      try {{
        const response = await fetch(
          `${{apiUrl}}/api/drawings/${{encodeURIComponent(drawingId)}}/coordinates/from-drawing`,
          {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ x_mm: xMm, y_mm: yMm }}),
          }}
        );
        let body = {{}};
        try {{ body = await response.json(); }} catch (_) {{}}
        if (!response.ok) {{
          const detail = body.detail || body.message || '좌표 조회에 실패했습니다.';
          setAddressStatus(String(detail), 'error');
          return;
        }}
        if (body.x_mm == null || body.y_mm == null) {{
          setAddressStatus('좌표 위치를 계산하지 못했습니다.', 'error');
          return;
        }}
        addProbeMarker(body);
        if (body.in_bounds) {{
          setAddressStatus(formatProbeLabel(body), 'ok');
        }} else {{
          setAddressStatus(
            formatProbeLabel(body) + ' · ' + (body.message || '도면 범위 밖'),
            'error'
          );
        }}
      }} catch (err) {{
        setAddressStatus('좌표 조회 요청에 실패했습니다.', 'error');
      }}
    }}

    function fitToView() {{
      if (!viewer || !viewer.GetBounds) {{
        return;
      }}
      const bounds = viewer.GetBounds();
      const origin = viewer.GetOrigin();
      if (!bounds || !origin) {{
        return;
      }}
      viewer.FitView(
        bounds.minX - origin.x,
        bounds.maxX - origin.x,
        bounds.minY - origin.y,
        bounds.maxY - origin.y
      );
      viewer.Render();
      const cam = viewer.GetCamera();
      baseViewWidth = Math.abs(cam.right - cam.left);
      if (activeSlot) {{
        activeSlot.baseViewWidth = baseViewWidth;
      }}
      updateZoomLabel();
      updateMarkerScreenPositions();
    }}

    function zoomByFactor(factor) {{
      if (!viewer || !viewer.GetCamera) {{
        return;
      }}
      const cam = viewer.GetCamera();
      const center = {{
        x: (cam.left + cam.right) / 2,
        y: (cam.bottom + cam.top) / 2,
      }};
      const width = Math.abs(cam.right - cam.left);
      viewer.SetView(center, Math.max(width / factor, 1e-6));
      viewer.Render();
      updateZoomLabel();
      updateMarkerScreenPositions();
    }}

    function setAddressStatus(text, tone) {{
      addressStatus.textContent = text || '';
      addressStatus.className = tone || '';
    }}

    function setAddressControlsEnabled(enabled) {{
      if (addressQuery) addressQuery.disabled = !enabled;
      if (addressSearch) addressSearch.disabled = !enabled;
      if (!enabled) {{
        closeAddressDropdown();
        setAddressStatus('도면 범위 준비 중… 잠시 후 주소 검색을 사용할 수 있습니다.', '');
      }}
    }}

    function drawingHasExtents(drawing) {{
      return (
        drawing
        && drawing.extents_min_x != null
        && drawing.extents_min_y != null
        && drawing.extents_max_x != null
        && drawing.extents_max_y != null
      );
    }}

    function applyUnitDetectionHint() {{
      if (addressReady && unitDetection === 'ambiguous') {{
        setAddressStatus('도면 단위가 모호합니다. 툴바에서 미터/밀리미터를 선택해 주세요.', 'error');
      }}
    }}

    function markAddressReady(drawing) {{
      if (addressReady) {{
        return;
      }}
      addressReady = true;
      if (activeSlot) {{
        activeSlot.addressReady = true;
      }}
      stopPreparePolling();
      if (drawing && drawing.coordinate_scale != null && coordinateScale) {{
        currentCoordinateScale = Number(drawing.coordinate_scale) === 1 ? 1 : 1000;
        coordinateScale.value = String(currentCoordinateScale);
        if (activeSlot) activeSlot.coordinateScale = currentCoordinateScale;
      }}
      if (drawing && drawing.coordinate_system && coordinateSystem) {{
        currentCoordinateSystem = drawing.coordinate_system;
        coordinateSystem.value = currentCoordinateSystem;
        if (activeSlot) activeSlot.coordinateSystem = currentCoordinateSystem;
      }}
      if (drawing && drawing.unit_detection != null) {{
        unitDetection = String(drawing.unit_detection);
        if (activeSlot) activeSlot.unitDetection = unitDetection;
      }}
      setAddressControlsEnabled(true);
      setAddressStatus('');
      applyUnitDetectionHint();
    }}

    async function refreshPrepareStatus() {{
      if (addressReady || !drawingId) {{
        return true;
      }}
      try {{
        const response = await fetch(
          `${{apiUrl}}/api/drawings/${{encodeURIComponent(drawingId)}}/prepare`
        );
        if (!response.ok) {{
          return false;
        }}
        const body = await response.json();
        const drawing = body.drawing || {{}};
        if (body.prepared === true || drawingHasExtents(drawing)) {{
          markAddressReady(drawing);
          return true;
        }}
        if (String(drawing.prepare_status || '') === 'failed') {{
          setAddressStatus(
            '주소 검색용 도면 범위 준비에 실패했습니다. 다시 시도를 눌러 주세요.',
            'error'
          );
        }}
      }} catch (_) {{
        // Keep polling; transient network errors should not remount the viewer.
      }}
      return false;
    }}

    function startPreparePolling() {{
      if (addressReady || preparePollTimer != null || !drawingId) {{
        return;
      }}
      refreshPrepareStatus();
      preparePollTimer = setInterval(() => {{
        refreshPrepareStatus();
      }}, 2000);
    }}

    function selectAddress(item) {{
      if (!item) {{
        return;
      }}
      selectedAddress = item;
      hideContextMenu();
      setAddressStatus('');
      convertSelectedAddress(item);
    }}

    async function convertSelectedAddress(item) {{
      if (!addressReady || !drawingId) {{
        setAddressStatus('도면 범위 준비 중… 주소 마커를 아직 표시할 수 없습니다.', 'error');
        return;
      }}
      try {{
        const response = await fetch(
          `${{apiUrl}}/api/drawings/${{encodeURIComponent(drawingId)}}/coordinates/convert`,
          {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{
              longitude: item.longitude,
              latitude: item.latitude,
              display_name: item.display_name,
            }}),
          }}
        );
        let body = {{}};
        try {{ body = await response.json(); }} catch (_) {{}}
        if (!response.ok) {{
          const detail = body.detail || body.message || '좌표 변환에 실패했습니다.';
          setAddressStatus(String(detail), 'error');
          return;
        }}
        if (!body.in_bounds) {{
          setAddressStatus(body.message || '도면 범위 밖입니다.', 'error');
          return;
        }}
        if (body.x_mm == null || body.y_mm == null) {{
          setAddressStatus('좌표 위치를 계산하지 못했습니다.', 'error');
          return;
        }}
        addMarker(body, item.display_name);
        setAddressStatus(body.message || '마커를 표시했습니다.', 'ok');
      }} catch (err) {{
        setAddressStatus('좌표 변환 요청에 실패했습니다.', 'error');
      }}
    }}

    function highlightMatch(text, query) {{
      const source = String(text || '');
      const q = String(query || '').trim();
      if (!q) {{
        return source.replace(/[&<>"']/g, (ch) => ({{
          '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }})[ch]);
      }}
      const escaped = source.replace(/[&<>"']/g, (ch) => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }})[ch]);
      const idx = source.toLowerCase().indexOf(q.toLowerCase());
      if (idx < 0) {{
        return escaped;
      }}
      const before = escaped.slice(0, idx);
      const match = escaped.slice(idx, idx + q.length);
      const after = escaped.slice(idx + q.length);
      return before + '<mark>' + match + '</mark>' + after;
    }}

    function closeAddressDropdown() {{
      addressDropdown.hidden = true;
      addressQuery.setAttribute('aria-expanded', 'false');
      addressActiveIndex = -1;
    }}

    function openAddressDropdown() {{
      addressDropdown.hidden = false;
      addressQuery.setAttribute('aria-expanded', 'true');
    }}

    function renderAddressResults() {{
      addressResultsList.innerHTML = '';
      if (!addressItems.length) {{
        addressDropdownEmpty.hidden = !addressShowEmpty;
        if (addressShowEmpty) {{
          openAddressDropdown();
        }} else {{
          closeAddressDropdown();
        }}
        return;
      }}
      addressDropdownEmpty.hidden = true;
      addressItems.forEach((item, index) => {{
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'address-result-item' + (index === addressActiveIndex ? ' active' : '');
        button.setAttribute('role', 'option');
        button.innerHTML =
          '<span class="address-result-title">' +
          highlightMatch(item.display_name || '', addressHighlightQuery) +
          '</span>' +
          '<span class="address-result-subtitle">' +
          highlightMatch(item.address_name || item.road_address || '', addressHighlightQuery) +
          '</span>';
        button.addEventListener('click', () => {{
          addressQuery.value = item.display_name || '';
          closeAddressDropdown();
          selectAddress(item);
        }});
        addressResultsList.appendChild(button);
      }});
      openAddressDropdown();
    }}

    function moveAddressActive(delta) {{
      if (!addressItems.length) {{
        return;
      }}
      addressActiveIndex = (addressActiveIndex + delta + addressItems.length) % addressItems.length;
      renderAddressResults();
    }}

    async function searchAddress() {{
      if (!addressReady) {{
        setAddressStatus('도면 범위 준비 중… 잠시 후 다시 검색해 주세요.', 'error');
        return;
      }}
      const query = (addressQuery.value || '').trim();
      addressHighlightQuery = query;
      addressShowEmpty = false;
      addressItems = [];
      addressActiveIndex = -1;
      if (!query) {{
        setAddressStatus('주소를 입력해 주세요.', 'error');
        closeAddressDropdown();
        return;
      }}
      setAddressStatus('주소를 검색하는 중…', '');
      try {{
        const response = await fetch(
          `${{apiUrl}}/api/addresses/search?query=${{encodeURIComponent(query)}}`
        );
        let body = {{}};
        try {{ body = await response.json(); }} catch (_) {{}}
        if (!response.ok) {{
          setAddressStatus(String(body.detail || '주소 검색에 실패했습니다.'), 'error');
          closeAddressDropdown();
          return;
        }}
        addressItems = Array.isArray(body.items) ? body.items : (body.results || []);
        addressShowEmpty = addressItems.length === 0;
        renderAddressResults();
        if (!addressItems.length) {{
          setAddressStatus('검색 결과가 없습니다.', 'error');
        }} else {{
          setAddressStatus('원하는 주소를 선택하세요.', 'ok');
        }}
      }} catch (err) {{
        setAddressStatus('주소 검색 요청에 실패했습니다.', 'error');
        closeAddressDropdown();
      }}
    }}

    async function saveCoordinateSettings(payload) {{
      if (savingCoordinateSettings || !drawingId) {{
        return;
      }}
      savingCoordinateSettings = true;
      if (coordinateSystem) coordinateSystem.disabled = true;
      if (coordinateScale) coordinateScale.disabled = true;
      try {{
        const response = await fetch(
          `${{apiUrl}}/api/drawings/${{encodeURIComponent(drawingId)}}/coordinate-settings`,
          {{
            method: 'PATCH',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload),
          }}
        );
        let body = {{}};
        try {{ body = await response.json(); }} catch (_) {{}}
        if (!response.ok) {{
          setAddressStatus(String(body.detail || '좌표 설정 저장에 실패했습니다.'), 'error');
          if (coordinateSystem) coordinateSystem.value = currentCoordinateSystem;
          if (coordinateScale) coordinateScale.value = String(currentCoordinateScale);
          return;
        }}
        const drawing = body.drawing || {{}};
        if (drawing.coordinate_system) {{
          currentCoordinateSystem = drawing.coordinate_system;
          if (coordinateSystem) coordinateSystem.value = currentCoordinateSystem;
          if (activeSlot) activeSlot.coordinateSystem = currentCoordinateSystem;
        }}
        if (drawing.coordinate_scale != null) {{
          currentCoordinateScale = Number(drawing.coordinate_scale) === 1 ? 1 : 1000;
          if (coordinateScale) coordinateScale.value = String(currentCoordinateScale);
          if (activeSlot) activeSlot.coordinateScale = currentCoordinateScale;
        }}
        clearMarkers();
        setAddressStatus(body.message || '좌표 설정을 저장했습니다.', 'ok');
      }} catch (err) {{
        setAddressStatus('좌표 설정 저장 요청에 실패했습니다.', 'error');
        if (coordinateSystem) coordinateSystem.value = currentCoordinateSystem;
        if (coordinateScale) coordinateScale.value = String(currentCoordinateScale);
      }} finally {{
        savingCoordinateSettings = false;
        if (coordinateSystem) coordinateSystem.disabled = false;
        if (coordinateScale) coordinateScale.disabled = false;
      }}
    }}

    async function saveCoordinateSystem(nextSystem) {{
      await saveCoordinateSettings({{ coordinate_system: nextSystem }});
    }}

    async function saveCoordinateScale(nextScale) {{
      await saveCoordinateSettings({{ coordinate_scale: Number(nextScale) }});
    }}

    function resizeViewer() {{
      if (!viewer || !viewer.SetSize || !activeSlot) {{
        return;
      }}
      const rect = activeSlot.host.getBoundingClientRect();
      const width = Math.max(1, Math.floor(rect.width));
      const height = Math.max(1, Math.floor(rect.height));
      viewer.SetSize(width, height);
      if (viewer.Render) {{
        viewer.Render();
      }}
      updateMarkerScreenPositions();
      updateZoomLabel();
    }}

    function hideAllSlots() {{
      slots.forEach((slot) => {{
        slot.host.classList.remove('active');
      }});
    }}

    function syncToolbarFromSlot(slot) {{
      drawingId = slot.drawingId;
      addressReady = !!slot.addressReady;
      unitDetection = slot.unitDetection || '';
      currentCoordinateSystem = slot.coordinateSystem || 'EPSG:5179';
      currentCoordinateScale = Number(slot.coordinateScale) === 1 ? 1 : 1000;
      baseViewWidth = slot.baseViewWidth;
      viewer = slot.viewer;
      viewerReady = !!slot.viewerReady;
      lastPointerScene = null;
      if (coordinateSystem) coordinateSystem.value = currentCoordinateSystem;
      if (coordinateScale) coordinateScale.value = String(currentCoordinateScale);
      setAddressControlsEnabled(addressReady);
      if (addressReady) {{
        setAddressStatus('');
        applyUnitDetectionHint();
      }} else {{
        setAddressControlsEnabled(false);
      }}
    }}

    function evictSlot(key) {{
      const slot = slots.get(key);
      if (!slot) {{
        return;
      }}
      try {{
        if (slot.viewer && slot.viewer.Destroy) {{
          slot.viewer.Destroy();
        }}
      }} catch (_) {{}}
      if (slot.host && slot.host.parentNode) {{
        slot.host.parentNode.removeChild(slot.host);
      }}
      slots.delete(key);
      if (activeKey === key) {{
        activeKey = null;
        activeSlot = null;
        viewer = null;
        viewerReady = false;
        drawingId = '';
        stopPreparePolling();
      }}
    }}

    function evictLruIfNeeded() {{
      while (slots.size >= VIEWER_SLOT_LIMIT) {{
        let oldestKey = null;
        let oldestTouch = Infinity;
        slots.forEach((slot, key) => {{
          if (key === activeKey) {{
            return;
          }}
          const touched = Number(slot.touchedAt || 0);
          if (touched < oldestTouch) {{
            oldestTouch = touched;
            oldestKey = key;
          }}
        }});
        if (!oldestKey) {{
          // All slots are active somehow; drop an arbitrary non-matching key.
          oldestKey = slots.keys().next().value;
        }}
        if (!oldestKey) {{
          break;
        }}
        evictSlot(oldestKey);
      }}
    }}

    function evictDrawing(drawingIdValue) {{
      const target = String(drawingIdValue || '');
      Array.from(slots.keys()).forEach((key) => {{
        const slot = slots.get(key);
        if (slot && slot.drawingId === target) {{
          evictSlot(key);
        }}
      }});
    }}

    function evictMissingDrawings(availableIds) {{
      const allowed = new Set(
        String(availableIds || '')
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean)
      );
      if (!allowed.size) {{
        return;
      }}
      Array.from(slots.keys()).forEach((key) => {{
        const slot = slots.get(key);
        if (slot && !allowed.has(slot.drawingId)) {{
          evictSlot(key);
        }}
      }});
    }}

    function showSlot(slot) {{
      const drawingChanged = !activeSlot || activeSlot.drawingId !== slot.drawingId;
      hideAllSlots();
      slot.host.classList.add('active');
      activeKey = slot.key;
      activeSlot = slot;
      touchSlot(slot);
      stopPreparePolling();
      // Markers are ephemeral UI; keep only while the same drawing stays active.
      if (drawingChanged) {{
        clearMarkers();
      }}
      syncToolbarFromSlot(slot);
      if (slot.viewerReady) {{
        setLoadStatus('');
        resizeViewer();
        updateZoomLabel();
      }}
      if (!slot.addressReady) {{
        startPreparePolling();
      }}
    }}

    async function createAndLoadSlot(sel) {{
      if (!window.DxfViewer || !window.THREE) {{
        setLoadStatus('도면 뷰어 스크립트를 불러오지 못했습니다.');
        return null;
      }}
      const key = slotKey(sel.drawingId, sel.fingerprint);
      evictLruIfNeeded();
      const host = document.createElement('div');
      host.className = 'viewer-slot';
      host.dataset.slotKey = key;
      slotRoot.appendChild(host);
      const slot = {{
        key: key,
        drawingId: sel.drawingId,
        fingerprint: sel.fingerprint,
        dxfUrl: sel.dxfUrl,
        host: host,
        viewer: null,
        viewerReady: false,
        addressReady: !!sel.addressReady,
        coordinateSystem: sel.coordinateSystem || 'EPSG:5179',
        coordinateScale: Number(sel.coordinateScale) === 1 ? 1 : 1000,
        unitDetection: sel.unitDetection || '',
        baseViewWidth: null,
        touchedAt: Date.now(),
      }};
      slots.set(key, slot);
      showSlot(slot);
      setLoadStatus('도면을 불러오는 중…');
      const instance = new window.DxfViewer(host, {{
        autoResize: false,
        clearColor: new window.THREE.Color('#f8fafc'),
        clearAlpha: 1,
        canvasWidth: Math.max(1, Math.floor(host.clientWidth || 800)),
        canvasHeight: Math.max(1, Math.floor(host.clientHeight || 600)),
      }});
      slot.viewer = instance;
      viewer = instance;
      instance.Subscribe('viewChanged', () => {{
        if (activeSlot !== slot) {{
          return;
        }}
        updateMarkerScreenPositions();
        updateZoomLabel();
      }});
      instance.Subscribe('pointerdown', (event) => {{
        if (activeSlot !== slot) {{
          return;
        }}
        const detail = event.detail || {{}};
        lastPointerScene = detail.position || null;
      }});
      try {{
        await instance.Load({{ url: sel.dxfUrl }});
        if (!slots.has(key) || activeSlot !== slot) {{
          return slot;
        }}
        slot.viewerReady = true;
        viewerReady = true;
        setLoadStatus('');
        resizeViewer();
        fitToView();
        applyUnitDetectionHint();
      }} catch (err) {{
        console.error(err);
        if (activeSlot === slot) {{
          setLoadStatus('도면을 표시하지 못했습니다. DXF를 확인해 주세요.');
        }}
      }}
      return slot;
    }}

    async function activate(sel) {{
      if (!sel || !sel.drawingId || !sel.dxfUrl) {{
        setLoadStatus('도면을 선택하면 여기에 표시됩니다.');
        return;
      }}
      const key = slotKey(sel.drawingId, sel.fingerprint);
      const forceReload = String(sel.revision || '') !== ''
        && String(sel.revision) !== lastAppliedRevision
        && slots.has(key)
        && String(sel.forceReload || '') === '1';
      if (forceReload) {{
        evictSlot(key);
      }}
      lastAppliedRevision = String(sel.revision || '');

      const cached = slots.get(key);
      if (cached && cached.viewerReady) {{
        showSlot(cached);
        // Refresh address-ready from latest meta without remounting.
        if (sel.addressReady && !cached.addressReady) {{
          markAddressReady({{
            coordinate_system: sel.coordinateSystem,
            coordinate_scale: sel.coordinateScale,
            unit_detection: sel.unitDetection,
          }});
        }} else if (sel.addressReady) {{
          cached.addressReady = true;
          addressReady = true;
          setAddressControlsEnabled(true);
        }}
        return;
      }}
      if (cached && !cached.viewerReady) {{
        showSlot(cached);
        return;
      }}
      await createAndLoadSlot(sel);
    }}

    function readSelectionMeta() {{
      try {{
        const el = window.parent.document.getElementById(SELECTION_META_ID);
        if (!el) {{
          return null;
        }}
        return {{
          drawingId: el.getAttribute('data-drawing-id') || '',
          dxfUrl: el.getAttribute('data-dxf-url') || '',
          fingerprint: el.getAttribute('data-fingerprint') || '',
          coordinateSystem: el.getAttribute('data-coordinate-system') || 'EPSG:5179',
          coordinateScale: el.getAttribute('data-coordinate-scale') || '1000',
          unitDetection: el.getAttribute('data-unit-detection') || '',
          addressReady: el.getAttribute('data-address-ready') === 'true',
          revision: el.getAttribute('data-revision') || '',
          forceReload: el.getAttribute('data-force-reload') || '0',
          availableIds: el.getAttribute('data-available-ids') || '',
        }};
      }} catch (_) {{
        return null;
      }}
    }}

    function selectionSignature(sel) {{
      if (!sel) {{
        return '';
      }}
      return [
        sel.drawingId,
        sel.fingerprint,
        sel.revision,
        sel.forceReload,
        sel.availableIds,
      ].join('|');
    }}

    async function pollSelectionMeta() {{
      const sel = readSelectionMeta();
      if (!sel) {{
        return;
      }}
      evictMissingDrawings(sel.availableIds);
      const sig = selectionSignature(sel);
      if (
        activeSlot
        && sel.drawingId === activeSlot.drawingId
        && sel.fingerprint === activeSlot.fingerprint
      ) {{
        if (sel.addressReady && !activeSlot.addressReady) {{
          markAddressReady({{
            coordinate_system: sel.coordinateSystem,
            coordinate_scale: sel.coordinateScale,
            unit_detection: sel.unitDetection,
          }});
        }} else if (sel.coordinateSystem || sel.coordinateScale != null) {{
          if (sel.coordinateSystem) {{
            activeSlot.coordinateSystem = sel.coordinateSystem;
            currentCoordinateSystem = sel.coordinateSystem;
            if (coordinateSystem) coordinateSystem.value = currentCoordinateSystem;
          }}
          if (sel.coordinateScale != null) {{
            activeSlot.coordinateScale = Number(sel.coordinateScale) === 1 ? 1 : 1000;
            currentCoordinateScale = activeSlot.coordinateScale;
            if (coordinateScale) coordinateScale.value = String(currentCoordinateScale);
          }}
          if (sel.unitDetection != null) {{
            activeSlot.unitDetection = sel.unitDetection || '';
            unitDetection = activeSlot.unitDetection;
          }}
        }}
      }}
      if (sig === lastSelectionSig) {{
        return;
      }}
      lastSelectionSig = sig;
      await activate(sel);
    }}

    document.getElementById('zoom-in').addEventListener('click', () => zoomByFactor(1.25));
    document.getElementById('zoom-out').addEventListener('click', () => zoomByFactor(0.8));
    document.getElementById('fit').addEventListener('click', () => fitToView());
    addressSearch.addEventListener('click', () => searchAddress());
    addressQuery.addEventListener('keydown', (event) => {{
      if (event.key === 'Enter') {{
        event.preventDefault();
        if (addressActiveIndex >= 0 && addressItems[addressActiveIndex]) {{
          selectAddress(addressItems[addressActiveIndex]);
          closeAddressDropdown();
        }} else {{
          searchAddress();
        }}
      }} else if (event.key === 'ArrowDown') {{
        event.preventDefault();
        moveAddressActive(1);
      }} else if (event.key === 'ArrowUp') {{
        event.preventDefault();
        moveAddressActive(-1);
      }} else if (event.key === 'Escape') {{
        closeAddressDropdown();
      }}
    }});
    addressSearchBox.addEventListener('mouseleave', () => {{
      // Keep open while typing; close only via Escape/selection.
    }});
    if (coordinateSystem) {{
      coordinateSystem.addEventListener('change', () => {{
        saveCoordinateSystem(coordinateSystem.value);
      }});
    }}
    if (coordinateScale) {{
      coordinateScale.addEventListener('change', () => {{
        saveCoordinateScale(coordinateScale.value);
      }});
    }}
    markerDeleteBtn.addEventListener('click', (event) => {{
      event.preventDefault();
      if (contextMenuMarkerId) {{
        removeMarker(contextMenuMarkerId);
      }}
    }});
    markerContextMenu.addEventListener('pointerdown', (event) => {{
      event.stopPropagation();
    }});
    viewport.addEventListener('dblclick', (event) => {{
      if (!viewerReady) {{
        return;
      }}
      if (event.target.closest('.marker') || event.target.closest('#marker-context-menu')) {{
        return;
      }}
      const scene = lastPointerScene;
      if (!scene) {{
        return;
      }}
      const drawing = sceneToDrawing(scene.x, scene.y);
      if (!drawing) {{
        return;
      }}
      probeCoordinatesAt(drawing.x_mm, drawing.y_mm);
    }});
    document.addEventListener('pointerdown', (event) => {{
      if (
        !markerContextMenu.hidden
        && !markerContextMenu.contains(event.target)
        && !event.target.closest('.marker')
      ) {{
        hideContextMenu();
      }}
    }});
    window.addEventListener('resize', () => resizeViewer());
    setAddressControlsEnabled(false);
    setLoadStatus('도면을 선택하면 여기에 표시됩니다.');
    pollSelectionMeta();
    metaPollTimer = setInterval(pollSelectionMeta, 300);
  </script>
</body>
</html>
"""


def build_viewer_html(
    dxf_url: str = "",
    *,
    viewport_height_px: int,
    api_url: str,
    drawing_id: str = "",
    bundle_url: str,
    coordinate_system: str = "EPSG:5179",
    coordinate_scale: int = 1000,
    unit_detection: str | None = None,
    address_ready: bool = True,
    width: int | None = None,
    height: int | None = None,
) -> str:
    """Compatibility wrapper: selection is applied via parent meta, not srcdoc."""
    del (
        dxf_url,
        drawing_id,
        coordinate_system,
        coordinate_scale,
        unit_detection,
        address_ready,
        width,
        height,
    )
    return build_viewer_shell_html(
        viewport_height_px=viewport_height_px,
        api_url=api_url,
        bundle_url=bundle_url,
    )


def build_selection_meta_bridge_html(
    *,
    drawing_id: str,
    dxf_url: str,
    fingerprint: str,
    coordinate_system: str,
    coordinate_scale: int,
    unit_detection: str | None,
    address_ready: bool,
    revision: int,
    force_reload: bool,
    available_ids: list[str],
) -> str:
    """Tiny iframe script that upserts selection meta on the Streamlit parent DOM."""
    safe_id = html.escape(SELECTION_META_ID, quote=True)
    attrs = {
        "data-drawing-id": drawing_id,
        "data-dxf-url": dxf_url,
        "data-fingerprint": fingerprint,
        "data-coordinate-system": coordinate_system,
        "data-coordinate-scale": str(1 if int(coordinate_scale) == 1 else 1000),
        "data-unit-detection": unit_detection or "",
        "data-address-ready": "true" if address_ready else "false",
        "data-revision": str(int(revision)),
        "data-force-reload": "1" if force_reload else "0",
        "data-available-ids": ",".join(available_ids),
    }
    pairs: list[str] = []
    for key, value in attrs.items():
        safe_key = key.replace("\\", "\\\\").replace("'", "\\'")
        safe_val = (
            str(value)
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\r", "")
            .replace("\n", " ")
        )
        pairs.append(f"'{safe_key}': '{safe_val}'")
    attr_object = ",\n        ".join(pairs)
    return f"""<!doctype html>
<html><body>
<script>
(function () {{
  try {{
    const doc = window.parent.document;
    let el = doc.getElementById('{safe_id}');
    if (!el) {{
      el = doc.createElement('div');
      el.id = '{safe_id}';
      el.style.display = 'none';
      doc.body.appendChild(el);
    }}
    const attrs = {{
        {attr_object}
    }};
    Object.keys(attrs).forEach((key) => {{
      el.setAttribute(key, attrs[key]);
    }});
  }} catch (err) {{
    console.error(err);
  }}
}})();
</script>
</body></html>
"""
