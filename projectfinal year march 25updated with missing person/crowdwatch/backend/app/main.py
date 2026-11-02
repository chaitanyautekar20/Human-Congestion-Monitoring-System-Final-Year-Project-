import asyncio, os, time, json, threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .utils.db import init_db, save_alert
from .config import BROADCAST_STATS_INTERVAL

app = FastAPI()


static_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'frontend')
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ── shared state ──────────────────────────────────────────────────────────────
_clients: set = set()
_camera_counts: dict = {}
_lock = asyncio.Lock()

# threshold state
_crowd_threshold: int = 30
_auto_threshold: bool = False
_area_sqkm: float = 0.0          # 0 means not set; >0 triggers density-based auto
_threshold_history: list = []

# webcam state
_webcam_thread = None
_webcam_running = False
_webcam_error: str = None

# missing-person target embedding (set when user uploads a photo)
_missing_embedding = None
_missing_active: bool = False
# Raised from 0.55 — full-body reference photo vs tight crop needs more tolerance
MISSING_DIST_THRESHOLD = 0.80

# ── shared ReID model instance (reused everywhere) ────────────────────────────
_reid_model = None
_reid_model_lock = threading.Lock()

def _get_reid_model():
    global _reid_model
    if _reid_model is None:
        with _reid_model_lock:
            if _reid_model is None:
                from .models.tracker_reid import ReIDModel
                _reid_model = ReIDModel()
    return _reid_model

# ── WHO crowd density standard: 4 people / m² = 4,000,000 / km²
# threshold = area_sqkm * 4_000_000  (capped at 5000 for sanity)
def _density_threshold_from_area(area_sqkm: float) -> int:
    if area_sqkm <= 0:
        return _crowd_threshold
    raw = area_sqkm * 4_000_000
    return max(1, min(5000, int(raw)))


# ── helpers ───────────────────────────────────────────────────────────────────
async def publish_alert(alert_obj: dict):
    msg = json.dumps({"type": "ALERT", "payload": alert_obj})
    for ws in list(_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            _clients.discard(ws)


async def update_camera_count(camera_id: str, count: int):
    async with _lock:
        _camera_counts[camera_id] = count
    # rolling-window auto threshold (only when area not set)
    if _auto_threshold and _area_sqkm <= 0:
        _threshold_history.append(count)
        if len(_threshold_history) > 200:
            _threshold_history.pop(0)
        if len(_threshold_history) >= 10:
            import statistics
            mean = statistics.mean(_threshold_history)
            stdev = statistics.stdev(_threshold_history)
            global _crowd_threshold
            _crowd_threshold = max(5, int(mean + 1.5 * stdev))


def update_camera_count_sync(camera_id: str, count: int):
    _camera_counts[camera_id] = count


def _effective_threshold() -> int:
    if _area_sqkm > 0:
        return _density_threshold_from_area(_area_sqkm)
    return _crowd_threshold


# ── broadcast loop ────────────────────────────────────────────────────────────
# ── main event loop reference (stored at startup for thread-safe alert firing) ─
_main_loop: asyncio.AbstractEventLoop = None

@app.on_event("startup")
async def startup():
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    init_db()
    asyncio.create_task(_broadcast_stats_loop())


async def _broadcast_stats_loop():
    while True:
        async with _lock:
            cameras = [{"camera": k, "count": v} for k, v in _camera_counts.items()]
        total = sum(c["count"] for c in cameras)
        payload = json.dumps({
            "type": "STATS_UPDATE",
            "cameras": cameras,
            "total": total,
            "threshold": _effective_threshold(),
            "auto": _auto_threshold,
            "area_sqkm": _area_sqkm,
            "missing_active": _missing_active,
        })
        for ws in list(_clients):
            try:
                await ws.send_text(payload)
            except Exception:
                _clients.discard(ws)
        await asyncio.sleep(BROADCAST_STATS_INTERVAL)


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        _clients.discard(ws)


# ── threshold API ─────────────────────────────────────────────────────────────
@app.post("/threshold/set")
async def set_threshold(value: int = Form(...)):
    global _crowd_threshold, _auto_threshold, _area_sqkm
    _auto_threshold = False
    _area_sqkm = 0.0
    _crowd_threshold = max(1, value)
    return {"ok": True, "threshold": _crowd_threshold, "auto": False, "area_sqkm": 0}


@app.post("/threshold/auto")
async def set_auto_threshold(enabled: bool = Form(...)):
    global _auto_threshold, _area_sqkm
    _auto_threshold = enabled
    if enabled:
        _area_sqkm = 0.0   # auto-rolling takes over
    return {"ok": True, "auto": _auto_threshold, "threshold": _effective_threshold()}


@app.post("/threshold/area")
async def set_area_threshold(area_sqkm: float = Form(...)):
    """Set threshold automatically based on monitored area in km²."""
    global _area_sqkm, _auto_threshold
    _area_sqkm = max(0.0, area_sqkm)
    _auto_threshold = False
    t = _density_threshold_from_area(_area_sqkm)
    return {"ok": True, "area_sqkm": _area_sqkm, "threshold": t, "auto": "area"}


@app.get("/threshold")
async def get_threshold():
    return {
        "threshold": _effective_threshold(),
        "auto": _auto_threshold,
        "area_sqkm": _area_sqkm,
        "mode": "area" if _area_sqkm > 0 else ("auto" if _auto_threshold else "manual"),
    }


# ── missing person API ────────────────────────────────────────────────────────
@app.post("/missing/set")
async def missing_set(file: UploadFile = File(...)):
    """Upload a reference photo to start tracking a missing person."""
    global _missing_embedding, _missing_active
    import numpy as np, cv2
    contents = await file.read()
    arr = np.frombuffer(contents, dtype='uint8')
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return JSONResponse({"error": "invalid image"}, status_code=400)
    # use shared model instance — same weights as webcam/video tracker
    reid = _get_reid_model()
    emb = reid.embed(img)
    if emb is None:
        return JSONResponse({"error": "could not embed image — check photo quality"}, status_code=400)
    _missing_embedding = emb
    _missing_active = True
    return {"ok": True, "status": "Missing person tracking active"}


@app.post("/missing/clear")
async def missing_clear():
    global _missing_embedding, _missing_active
    _missing_embedding = None
    _missing_active = False
    return {"ok": True}


@app.post("/missing/search")
async def missing_search(file: UploadFile = File(...)):
    """One-shot search against the ReID index."""
    import numpy as np, cv2
    from .inference import reid_index
    contents = await file.read()
    arr = np.frombuffer(contents, dtype='uint8')
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return JSONResponse({"error": "invalid image"}, status_code=400)
    reid = _get_reid_model()
    emb = reid.embed(img)
    res = reid_index.search(emb, top_k=30)
    return {"results": res}


def _check_missing_in_frame(embeddings: list, camera: str, source: str = "webcam"):
    """Called from webcam thread. Fires alert via main event loop if match found."""
    if not _missing_active or _missing_embedding is None:
        return
    import numpy as np
    for emb in embeddings:
        if emb is None:
            continue
        dist = float(np.linalg.norm(_missing_embedding - emb))
        if dist < MISSING_DIST_THRESHOLD:
            alert = {
                "type": "MISSING_PERSON_FOUND",
                "camera": camera,
                "source": source,
                "distance": round(dist, 4),
                "level": "critical",
                "message": f"Missing person detected via {source} (dist={dist:.3f})",
                "timestamp": time.time(),
            }
            save_alert(camera, "MISSING_PERSON_FOUND", alert)
            if _main_loop and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(publish_alert(alert), _main_loop)
            break


# ── webcam ────────────────────────────────────────────────────────────────────
@app.post("/webcam/start")
async def webcam_start():
    global _webcam_thread, _webcam_running, _webcam_error
    if _webcam_running:
        return {"ok": False, "error": "Webcam already running"}

    _webcam_error = None
    _webcam_running = True
    _webcam_thread = threading.Thread(target=_run_webcam_thread, daemon=True)
    _webcam_thread.start()

    # wait up to 4 seconds for the camera to actually open
    for _ in range(40):
        await asyncio.sleep(0.1)
        if _webcam_error:
            _webcam_running = False
            return {"ok": False, "error": _webcam_error}
        # thread set running=False means it failed silently
        if not _webcam_running:
            return {"ok": False, "error": "Camera could not be opened. Check it is not in use by another app."}
        # camera opened and loop is running — count appears
        if "webcam" in _camera_counts:
            return {"ok": True, "status": "Webcam started"}

    # timed out waiting — if thread is still alive assume it's still loading models
    if _webcam_thread.is_alive():
        return {"ok": True, "status": "Webcam starting (models loading)..."}
    return {"ok": False, "error": "Webcam thread exited unexpectedly"}


@app.post("/webcam/stop")
async def webcam_stop():
    global _webcam_running
    _webcam_running = False
    _camera_counts.pop("webcam", None)
    return {"ok": True, "status": "Webcam stopped"}


@app.get("/webcam/status")
async def webcam_status():
    return {"running": _webcam_running}


def _run_webcam_thread():
    global _webcam_running, _webcam_error
    import cv2
    from .models.detector import Detector
    from .models.tracker_reid import MultiTracker
    from .inference import reid_index

    # ── try to open camera ───────────────────────────────────────────────────
    # Try DirectShow backend first (more reliable on Windows), fall back to default
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        # try index 1 as fallback (external USB cam)
        cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
    if not cap.isOpened():
        _webcam_error = "No camera found. Make sure a camera is connected and not used by another app."
        _webcam_running = False
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # ── load models ──────────────────────────────────────────────────────────
    try:
        detector = Detector()
        tracker = MultiTracker()
    except Exception as e:
        _webcam_error = f"Model loading failed: {e}"
        _webcam_running = False
        cap.release()
        return

    _last_alert_time = 0.0

    while _webcam_running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        try:
            dets = detector.detect(frame)
            tracked = tracker.process(frame, dets)
        except Exception as e:
            print(f"[webcam] detection error: {e}")
            time.sleep(0.05)
            continue

        smooth = tracked[0]["smooth_count"] if tracked else tracker.smoother.update(0)
        update_camera_count_sync("webcam", smooth)

        ts = time.time()
        embeddings = []
        for t in tracked:
            emb = t.get("embedding")
            if emb is not None:
                reid_index.add(emb, {
                    "camera": "webcam", "timestamp": ts,
                    "track_id": t["track_id"], "bbox": t["bbox"],
                })
                embeddings.append(emb)

        _check_missing_in_frame(embeddings, "webcam", "webcam")

        thr = _effective_threshold()
        if smooth >= thr and (ts - _last_alert_time) > 5.0:
            _last_alert_time = ts
            alert = {
                "type": "CROWD_DENSITY",
                "camera": "webcam",
                "count": smooth,
                "level": "high",
                "message": f"High crowd: {smooth} people (threshold: {thr})",
                "timestamp": ts,
            }
            save_alert("webcam", "CROWD_DENSITY", alert)
            if _main_loop and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(publish_alert(alert), _main_loop)

        time.sleep(0.05)

    cap.release()
    _webcam_running = False
    _camera_counts.pop("webcam", None)


# ── static files ──────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/dashboard.js")
async def dashboard_js():
    return FileResponse(os.path.join(static_dir, "dashboard.js"))

@app.get("/style.css")
async def style_css():
    return FileResponse(os.path.join(static_dir, "style.css"))
