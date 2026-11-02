from collections import deque
import time

_history: dict = {}


def update_and_check(camera_id: str, tracked_list: list, threshold: int = 30, max_history: int = 10):
    """
    Check crowd heuristics and return an alert dict or None.
    tracked_list: list of dicts with at least a 'bbox' key (or raw detection dicts).
    threshold: crowd density alert threshold (configurable).
    """
    ts = time.time()
    count = len(tracked_list)

    if camera_id not in _history:
        _history[camera_id] = deque(maxlen=max_history)
    _history[camera_id].append((ts, count))

    # ── density threshold ──────────────────────────────────────────────────────
    if count >= threshold:
        return {
            "type": "CROWD_DENSITY",
            "camera": camera_id,
            "count": count,
            "level": "high",
            "message": f"High crowd: {count} people (threshold: {threshold})",
        }

    # ── sudden surge ───────────────────────────────────────────────────────────
    hist = _history[camera_id]
    if len(hist) >= 3:
        t0, c0 = hist[0]
        tn, cn = hist[-1]
        dt = tn - t0
        if dt > 0 and (cn - c0) / max(1.0, dt) > 5.0:
            return {
                "type": "SUDDEN_SURGE",
                "camera": camera_id,
                "count": cn,
                "delta": cn - c0,
                "level": "high",
                "message": "Sudden crowd surge detected",
            }

    # ── overlap / pushing heuristic ────────────────────────────────────────────
    boxes = [t["bbox"] for t in tracked_list if "bbox" in t]
    overlaps = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _iou(boxes[i], boxes[j]) > 0.45:
                overlaps += 1
    # realistic threshold: overlaps > 20% of possible pairs
    n = len(boxes)
    max_pairs = max(1, n * (n - 1) // 2)
    if overlaps > 0 and overlaps / max_pairs > 0.20:
        return {
            "type": "PUSHING_LIKELY",
            "camera": camera_id,
            "overlaps": overlaps,
            "level": "high",
            "message": "Possible pushing / overcrowding detected",
        }

    return None


def _iou(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    w = max(0, x2 - x1); h = max(0, y2 - y1)
    inter = w * h
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter + 1e-6
    return inter / union
