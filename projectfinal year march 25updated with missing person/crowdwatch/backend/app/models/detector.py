from ultralytics import YOLO
import torch
import cv2
import numpy as np
from ..config import YOLO_MODEL_PATH

# reuse CLAHE object — creating it per frame is wasteful
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


class Detector:
    def __init__(self, model_path=None):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_path = model_path or YOLO_MODEL_PATH
        self.model = YOLO(self.model_path)
        # warm up with small dummy so first real frame isn't slow
        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        self.model(dummy, verbose=False)

    def detect(self, frame, conf=0.45, iou=0.45, imgsz=640):
        """Full-quality detection — used for webcam."""
        frame_proc = _preprocess(frame)
        return _run(self.model, frame_proc, conf, iou, imgsz)

    def detect_fast(self, frame, conf=0.40, iou=0.45, imgsz=320):
        """
        Fast detection for video processing:
        - imgsz=320  : half the input size → ~4x faster inference
        - no CLAHE   : skip preprocessing to save time
        - conf=0.40  : slightly lower to compensate for smaller input
        """
        return _run(self.model, frame, conf, iou, imgsz)


def _preprocess(frame):
    """CLAHE on L channel — reuses global CLAHE object."""
    try:
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = _clahe.apply(l)
        lab = cv2.merge([l, a, b])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    except Exception:
        return frame


def _run(model, frame, conf, iou, imgsz):
    results = model(
        frame,
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        classes=[0],
        agnostic_nms=True,
        verbose=False,
    )
    out = []
    for r in results:
        boxes = getattr(r, 'boxes', None)
        if boxes is None:
            continue
        for b in boxes:
            xyxy = b.xyxy[0].cpu().numpy().tolist()
            confv = float(b.conf[0].cpu().numpy())
            x1, y1, x2, y2 = map(int, xyxy)
            if (x2 - x1) < 10 or (y2 - y1) < 20:
                continue
            out.append({"bbox": [x1, y1, x2, y2], "conf": confv})
    return out
