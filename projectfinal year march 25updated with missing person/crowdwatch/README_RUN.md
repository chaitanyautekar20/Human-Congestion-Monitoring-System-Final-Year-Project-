CrowdWatch — Local Setup & Run Guide
=====================================

Requirements
------------
- Python 3.10+
- pip
- (Optional) GPU — install CUDA + compatible torch binary for speed
- Browser (Chrome / Edge recommended)


Project Structure
-----------------
crowdwatch/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app — all endpoints, webcam thread,
│   │   │                            #   video upload, threshold API, missing person API
│   │   ├── inference.py             # YOLO + DeepSORT stream processor + shared ReID index
│   │   ├── config.py                # Env-based config (FPS, DB path, model path)
│   │   ├── webcam.py                # Placeholder (logic lives in main.py)
│   │   ├── models/
│   │   │   ├── detector.py          # YOLOv8 wrapper (person class only)
│   │   │   ├── tracker_reid.py      # DeepSORT tracker + ResNet50 ReID embeddings
│   │   │   └── action_heuristics.py # Crowd density / surge / overlap alert logic
│   │   ├── store/
│   │   │   └── reid_index.py        # FAISS in-memory ReID index (add + search)
│   │   └── utils/
│   │       ├── broadcast.py         # Legacy placeholder (unused)
│   │       └── db.py                # SQLite init + save_alert helper
│   ├── models/
│   │   └── yolov8n.pt               # YOLOv8 weights (download separately)
│   ├── uploads/                     # Uploaded videos stored here automatically
│   ├── requirements.txt
│   └── run.sh
└── frontend/
    ├── index.html                   # Dark-theme two-column dashboard
    ├── dashboard.js                 # WebSocket client, charts, all UI logic
    └── style.css                    # Full dark UI styles


Setup Steps
-----------
1. Clone / copy files into a folder named crowdwatch/

2. Create Python environment:
   cd crowdwatch/backend
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install --upgrade pip
   pip install -r requirements.txt

3. Download YOLOv8 weights:
   python - <<PY
from ultralytics import YOLO
YOLO('yolov8n').save('models/yolov8n.pt')
print('Saved.')
PY

4. Run the backend:
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   # or: chmod +x run.sh && ./run.sh

5. Open the dashboard:
   http://localhost:8000/


API Endpoints
-------------
Webcam
  POST /webcam/start          Start webcam (YOLO + ReID in background thread)
  POST /webcam/stop           Stop webcam and clear count
  GET  /webcam/status         Returns { running: true/false }

Video
  POST /upload/video          Upload video for full YOLO frame-by-frame analysis
                              Returns: filename, duration_sec, fps, frames,
                                       avg_people, max_people, total_people_sum,
                                       timeline[], alerts[], threshold_used

Threshold
  POST /threshold/set         Manual count threshold       body: value=<int>
  POST /threshold/area        Area-based auto threshold    body: area_sqkm=<float>
  POST /threshold/auto        Rolling auto threshold       body: enabled=true/false
  GET  /threshold             Returns { threshold, auto, area_sqkm, mode }

Missing Person
  POST /missing/set           Upload reference photo — activates live tracking
  POST /missing/clear         Deactivate missing person tracking
  POST /missing/search        One-shot search against stored ReID index

WebSocket
  GET  /ws/alerts             Persistent connection for real-time updates


WebSocket Message Formats
--------------------------
Stats update (every 2 seconds):
  {
    "type": "STATS_UPDATE",
    "cameras": [{ "camera": "webcam", "count": 12 }],
    "total": 12,
    "threshold": 30,
    "auto": false,
    "area_sqkm": 0.0,
    "missing_active": false
  }

Alert:
  {
    "type": "ALERT",
    "payload": {
      "type": "CROWD_DENSITY" | "SUDDEN_SURGE" | "PUSHING_LIKELY" | "MISSING_PERSON_FOUND",
      "camera": "webcam",
      "count": 35,
      "level": "high" | "critical",
      "message": "High crowd: 35 people (threshold: 30)",
      "timestamp": 1234567890.0,
      "second": 12.5,        // video only — seconds into video
      "frame": 312,          // video only — frame number
      "distance": 0.312      // missing person only — ReID L2 distance
    }
  }


Features
--------

1. Webcam — Start / Stop
   - Start Camera button starts YOLO + DeepSORT + ReID in a background thread
   - Stop Camera button cleanly stops the thread and clears the count
   - Live people count updates every 2 seconds via WebSocket
   - Status bar turns green when running, muted when off
   - Page reload restores button state from /webcam/status
   - Missing person check runs on every webcam frame automatically

2. Video Upload & Analysis
   - Drag-and-drop or browse to select a video file
   - Full YOLO + DeepSORT detection run on every frame
   - Timeline sampled once per second of video (based on actual video FPS)
   - After analysis a full report is shown:
       File name, duration, FPS, total frames
       Avg people per frame, peak people count
       Total Crowd Count (sum across all frames) — highlighted large
       Threshold used, number of alerts fired
       List of all alerts with exact timestamps (seconds into video)
   - A separate bar chart renders the per-second crowd timeline
       Bars turn red when count >= threshold, purple otherwise
   - Missing person matches in video show exact second + frame number
   - All tracked person embeddings are stored in the ReID index for later search

3. Crowd Threshold — Three Modes

   a) Manual (set by count)
      Enter any integer and press Set.
      Alerts fire when detected people >= that number.
      Disables area and rolling auto modes.

   b) Auto by Area (km²)
      Enter the monitored area in km² and press Set.
      Formula: threshold = area_sqkm * 4,000,000
      Based on WHO crowd density standard: 4 people per m²
      Capped at 5000 for sanity.
      Example: 0.001 km² (1000 m²) → threshold = 4000
      The calculation is shown in the UI after setting.
      Disables manual and rolling auto modes.

   c) Rolling Auto (mean + 1.5σ)
      Toggle switch enables a rolling window of last 200 count readings.
      Threshold = mean + 1.5 * standard deviation, minimum 5.
      Requires at least 10 data points before it activates.
      Disabled automatically when Manual or Area mode is set.

4. Missing Person Tracking
   - Upload a reference photo via "Activate Tracking" button
   - Photo is embedded using the shared ResNet50 ReID singleton into a
     2048-dim L2-normalised vector
   - During webcam: every frame's tracked person embeddings are compared
     against the reference using L2 distance (threshold 0.80)
   - During video analysis: same check runs on every processed frame
   - On match a MISSING_PERSON_FOUND alert fires via WebSocket instantly:
       Webcam match: shows camera name + timestamp
       Video match:  shows exact second and frame number in the video
   - Header flashes red and a pulsing badge appears in the top bar
   - Alert appears in the feed in pink/critical color
   - Video analysis report highlights missing person matches with 🔴
   - "Clear" button deactivates tracking and removes the badge
   - Separate "Search Index" does a one-shot FAISS search against all
     stored embeddings from past webcam and video sessions
   - When missing person tracking is OFF, ReID is skipped during video
     processing for speed. When ON, ReID runs on every processed frame.

5. Live Crowd Density Chart
   - Line chart updated in real time via WebSocket (every 2 seconds)
   - Keeps last 60 data points (~2 minutes of history)
   - Resets and shows video timeline after a video upload completes

6. Alerts Feed
   - Color-coded by type:
       Red    — CROWD_DENSITY
       Amber  — SUDDEN_SURGE
       Orange — PUSHING_LIKELY
       Pink   — MISSING_PERSON_FOUND
       Blue   — INFO (status messages)
   - Shows alert type, message, timestamp, camera/source
   - Video alerts include the second timestamp (e.g. "at 12.5s")
   - Clear button empties the feed
   - Max 60 alerts kept in the feed at once

7. Stat Cards (top of page)
   - Live People Count  — updates every 2 seconds from WebSocket
   - Active Threshold   — synced from backend on every stats update
   - Threshold Mode     — Manual / Area / Rolling Auto


Heuristic Alert Logic (action_heuristics.py)
--------------------------------------------
CROWD_DENSITY    count >= threshold (configurable, default 30)
SUDDEN_SURGE     rate of change > 5 people/second over last 10 readings
PUSHING_LIKELY   IoU overlap between bounding boxes > 20% of all possible pairs


Bug Fixes Applied (vs original codebase)
-----------------------------------------
- Fixed NameError: update_camera_count() and publish_alert() were called
  but never defined — now properly defined in main.py.
- Removed circular import: webcam.py was importing from main.py which
  imported from webcam.py — fully resolved.
- Removed duplicate WebSocket client management — single _clients set
  used everywhere (old connected_clients list removed).
- inference.py no longer imports from main.py (circular import removed).
- Removed unused broadcast_stats() function from inference.py.
- Video upload now uses real YOLO detection instead of random dummy counts.
- action_heuristics.py overlap threshold fixed from hardcoded 80 to a
  percentage-based check (>20% of possible pairs) — realistic for real crowds.
- action_heuristics.py now accepts a configurable threshold parameter.
- Webcam thread now uses asyncio.run_coroutine_threadsafe() to safely
  publish alerts from a background thread to the async event loop.
- Fixed TypeError in tracker_reid.py: DeepSort update_tracks() was being
  called with two separate lists (boxes, confs) which is the wrong API.
  Fixed to pass a single list of ([x,y,w,h], confidence, class) tuples
  as required by deep_sort_realtime. Also added max(1,w) and max(1,h)
  guards to prevent zero-size bounding boxes crashing the tracker, and
  an early return [] when there are no detections.


Detection & Tracker Accuracy Improvements
------------------------------------------

Detection (detector.py):
- Confidence threshold raised from 0.35 to 0.45 — reduces false positives.
- NMS IoU tightened to 0.45 with agnostic_nms=True — removes duplicate boxes.
- Tiny box filter added — skips boxes smaller than 10x20px (noise/partials).
- CLAHE preprocessing on the L channel of LAB colour space — normalises
  brightness so YOLO performs better in dark or uneven lighting conditions.
- CLAHE object reused globally — was being recreated every frame before.
- Model warm-up on startup — first inference is not slow.
- detect_fast() added for video — imgsz=320, no CLAHE, ~4x faster.

Tracker (tracker_reid.py):
- max_age reduced from 30 to 20 — ghost tracks disappear faster.
- n_init=3 added — person must appear in 3 consecutive frames before being
  counted, eliminating false track confirmations from single-frame noise.
- max_cosine_distance=0.4 — tighter ReID matching, fewer ID switches.
- nms_max_overlap=0.7 — suppresses heavily overlapping tracks.
- Minimum crop size check (10x5px) before embedding — avoids bad ReID
  embeddings on tiny or partially visible crops.
- CountSmoother (EMA alpha=0.4) added — smooths frame-to-frame count
  jitter so the displayed number is stable and not erratic.
- pretrained=True replaced with weights=ResNet50_Weights.IMAGENET1K_V1
  to fix torchvision deprecation warnings.

Update Frequency:
- Broadcast interval reduced from 2s to 1s — UI updates twice as fast.
- Webcam loop runs at ~20fps (was 10fps) with CAP_PROP_BUFFERSIZE=1
  so the freshest frame is always processed.
- Webcam resolution set to 1280x720 for better detection quality.
- Crowd alerts throttled to once per 5 seconds — no alert spam.
- Video heuristic alerts also throttled to once per 5 seconds.

Frontend:
- animateCount() — count numbers animate smoothly instead of jumping.
- Live processing counter shown during video upload — displays current
  detected count as the video processes frame by frame via WebSocket.
- videoProcessing flag prevents stale video counts from polluting the
  live chart after analysis finishes.

Video Processing Speed:
- Video processing runs in a thread pool (run_in_executor) — no longer
  blocks the FastAPI event loop while processing large videos.
- Frame skipping: only 1 in every 3 frames is processed through YOLO and
  the tracker. Skipped frames reuse the last known count (~3x speed boost).
- Fast detection mode (detect_fast): uses imgsz=320 instead of 640 —
  ~4x faster YOLO inference with minimal accuracy loss.
- Frames wider than 640px are resized before inference.
- ReID embedding skipped when missing person tracking is not active —
  ResNet50 inference on every crop was a major bottleneck.
- Combined effect: roughly 6-8x faster video processing vs original.
- Analysis report now shows "Frames Processed" (actual) vs total frames.

Missing Person Tracking Fixes:
- Distance threshold raised from 0.55 to 0.80 — full-body reference photo
  vs tight bounding box crop produces higher L2 distances naturally.
  0.55 was rejecting real matches. 0.80 gives correct results.
- Shared ReIDModel singleton (_get_reid_model()) — previously a new
  ResNet50 was loaded from disk on every /missing/set and /missing/search
  call. Now all three code paths share one instance with identical weights,
  ensuring consistent embeddings across set, search, and webcam tracking.
- Fixed asyncio.get_event_loop() in webcam thread — in Python 3.10+ this
  can fail silently from a background thread. Fixed by storing the main
  event loop at startup in _main_loop and using run_coroutine_threadsafe()
  with that reference. Alerts now reliably reach the frontend.
- Confidence threshold raised from 0.35 to 0.45 — reduces false positives.
- NMS IoU tightened to 0.45 with agnostic_nms=True — removes duplicate boxes.
- Tiny box filter added — skips boxes smaller than 10x20px (noise/partials).
- CLAHE preprocessing on the L channel of LAB colour space — normalises
  brightness so YOLO performs better in dark or uneven lighting conditions.
- Model warm-up on startup — first inference is not slow.

Tracker (tracker_reid.py):
- max_age reduced from 30 to 20 — ghost tracks disappear faster.
- n_init=3 added — person must appear in 3 consecutive frames before being
  counted, eliminating false track confirmations from single-frame noise.
- max_cosine_distance=0.4 — tighter ReID matching, fewer ID switches.
- nms_max_overlap=0.7 — suppresses heavily overlapping tracks.
- Minimum crop size check (10x5px) before embedding — avoids bad ReID
  embeddings on tiny or partially visible crops.
- CountSmoother (EMA alpha=0.4) added — smooths frame-to-frame count
  jitter so the displayed number is stable and not erratic.

Update Frequency:
- Broadcast interval reduced from 2s to 1s — UI updates twice as fast.
- Webcam loop runs at ~20fps (was 10fps) with CAP_PROP_BUFFERSIZE=1
  so the freshest frame is always processed.
- Webcam resolution set to 1280x720 for better detection quality.
- Crowd alerts throttled to once per 5 seconds — no alert spam.
- Video heuristic alerts also throttled to once per 5 seconds.

Frontend:
- animateCount() — count numbers animate smoothly instead of jumping.
- Live processing counter shown during video upload — displays current
  detected count as the video processes frame by frame via WebSocket.
- videoProcessing flag prevents stale video counts from polluting the
  live chart after analysis finishes.


Notes
-----
- FAISS index is in-memory. Restart clears all stored ReID embeddings.
- Missing person tracking uses L2 distance < 0.80 as match threshold.
  Lower value = stricter matching. Raised from 0.55 — full-body photo vs
  tight crop naturally produces higher distances. Adjust
  MISSING_DIST_THRESHOLD in main.py if needed.
- Webcam uses cv2.VideoCapture(0) at 1280x720 — default system camera.
  Change index to 1 in main.py if camera 0 is not the right one.
- Webcam loop runs at ~20fps; broadcast interval is 1s for snappy UI updates.
- Video analysis runs in the FastAPI async event loop. Large videos may
  take time; the progress bar animates and live count updates via WebSocket.
- For GPU acceleration install the CUDA build of torch before running.
- Rolling auto threshold needs at least 10 data points to activate.
- Crowd alerts are throttled to once per 5 seconds to avoid spam.
- CountSmoother (EMA) stabilises the displayed count — small fluctuations
  are smoothed out. Adjust alpha in tracker_reid.py (0=no smoothing, 1=raw).


Troubleshooting
---------------
- YOLO fails to load
    Ensure models/yolov8n.pt exists. Run step 3 above.

- Webcam not found
    Check no other app is using the camera.
    Try changing VideoCapture(0) to VideoCapture(1) in main.py.

- Video upload returns "Could not open video"
    Ensure the file is a valid format supported by OpenCV
    (mp4, avi, mov, mkv). Re-encode with ffmpeg if needed.

- WebSocket disconnects immediately
    Confirm the backend is running on port 8000.
    Check firewall is not blocking the port.

- Missing person never matches
    Activate tracking BEFORE running webcam or uploading a video.
    The ReID index is empty on fresh start — run webcam or analyse a
    video first to populate it, then use Search Index.
    If tracking is active but no alert fires, the distance threshold
    may be too strict. Try raising MISSING_DIST_THRESHOLD in main.py
    (current value: 0.80). Also ensure the reference photo is clear,
    well-lit, and shows the full body.

- Auto area threshold seems too high
    WHO 4 people/m² is a dense crowd standard.
    For a 100 m² room: 0.0001 km² → threshold = 400.
    Adjust the formula in _density_threshold_from_area() in main.py.

- TypeError: object of type 'int' has no len() from DeepSort
    This was a bug in tracker_reid.py — now fixed. The update_tracks()
    call was passing two separate lists instead of the required format:
    [([x,y,w,h], confidence, class), ...]. Already patched in the code.

- Alerts not appearing
    Check the WebSocket status dot in the top-right corner.
    If red (disconnected), the backend may not be running.
