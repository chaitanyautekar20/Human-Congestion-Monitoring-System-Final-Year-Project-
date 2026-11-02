import cv2, asyncio, time
from .models.detector import Detector
from .models.tracker_reid import MultiTracker
from .models.action_heuristics import update_and_check
from .store.reid_index import ReIDIndex
from .utils.db import save_alert
from .config import PROCESS_FPS

detector = Detector()
tracker = MultiTracker()
reid_index = ReIDIndex(dim=2048)


async def process_stream(uri, camera_id, publish_alert, update_camera_count):
    """
    uri: "0" for webcam or rtsp/http url
    publish_alert: async fn(alert_dict)
    update_camera_count: async fn(camera_id, count)
    """
    try:
        cap = cv2.VideoCapture(int(uri))
    except (ValueError, TypeError):
        cap = cv2.VideoCapture(uri)

    if not cap.isOpened():
        await asyncio.sleep(1.0)
        return

    frame_time = 1.0 / max(1.0, PROCESS_FPS)

    while True:
        ret, frame = cap.read()
        if not ret:
            await asyncio.sleep(0.5)
            continue

        dets = detector.detect(frame)
        tracked = tracker.process(frame, dets)
        ts = time.time()

        for t in tracked:
            if t.get("embedding") is not None:
                meta = {
                    "camera": camera_id,
                    "timestamp": ts,
                    "track_id": t["track_id"],
                    "bbox": t["bbox"],
                }
                reid_index.add(t["embedding"], meta)

        await update_camera_count(camera_id, len(tracked))

        alert = update_and_check(camera_id, tracked)
        if alert:
            alert["timestamp"] = ts
            save_alert(camera_id, alert["type"], alert)
            await publish_alert(alert)

        await asyncio.sleep(frame_time)
