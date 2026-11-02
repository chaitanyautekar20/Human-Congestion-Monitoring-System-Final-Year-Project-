from deep_sort_realtime.deepsort_tracker import DeepSort
import numpy as np
import cv2
import torch
from torchvision import transforms, models
from collections import deque


class ReIDModel:
    def __init__(self, device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        # ResNet50 with identity FC — outputs 2048-dim embedding
        self.model = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V1)
        self.model.fc = torch.nn.Identity()
        self.model.to(self.device).eval()
        self.tf = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((128, 256)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225]),
        ])

    def embed(self, crop_bgr):
        if crop_bgr is None or crop_bgr.size == 0:
            return None
        h, w = crop_bgr.shape[:2]
        if h < 10 or w < 5:
            return None
        try:
            rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
            t = self.tf(rgb).unsqueeze(0).to(self.device)
            with torch.no_grad():
                emb = self.model(t).cpu().numpy().squeeze()
            # L2-normalise so cosine similarity == dot product
            norm = np.linalg.norm(emb) + 1e-6
            return (emb / norm).astype('float32')
        except Exception:
            return None


class CountSmoother:
    """Exponential moving average to reduce count jitter."""
    def __init__(self, alpha=0.4):
        self.alpha = alpha
        self._val = None

    def update(self, raw: int) -> int:
        if self._val is None:
            self._val = float(raw)
        else:
            self._val = self.alpha * raw + (1 - self.alpha) * self._val
        return int(round(self._val))


class MultiTracker:
    def __init__(self):
        self.tracker = DeepSort(
            max_age=20,          # drop ghost tracks faster (was 30)
            n_init=3,            # require 3 consecutive detections before confirming
            nms_max_overlap=0.7, # suppress heavily overlapping tracks
            max_cosine_distance=0.4,  # tighter ReID matching
        )
        self.reid = ReIDModel()
        self.smoother = CountSmoother(alpha=0.4)

    def process(self, frame, detections):
        """
        detections: list of {"bbox":[x1,y1,x2,y2], "conf":float}
        returns: list of confirmed tracked objects with smoothed count
          {"track_id", "bbox", "conf", "embedding", "smooth_count"}
        """
        # Build deep_sort_realtime format: [([x,y,w,h], conf, class), ...]
        raw = []
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            raw.append(([x1, y1, w, h], float(d["conf"]), "person"))

        if not raw:
            self.smoother.update(0)
            return []

        tracks = self.tracker.update_tracks(raw, frame=frame)

        out = []
        fh, fw = frame.shape[:2]
        confirmed_count = 0

        for t in tracks:
            if not t.is_confirmed():
                continue
            confirmed_count += 1
            tid = t.track_id
            ltrb = t.to_ltrb()
            x1, y1, x2, y2 = map(int, ltrb)
            x1c = max(0, x1); y1c = max(0, y1)
            x2c = min(fw - 1, x2); y2c = min(fh - 1, y2)
            if x2c <= x1c or y2c <= y1c:
                emb = None
            else:
                crop = frame[y1c:y2c, x1c:x2c].copy()
                emb = self.reid.embed(crop)
            out.append({
                "track_id": tid,
                "bbox": [x1c, y1c, x2c, y2c],
                "conf": float(getattr(t, 'det_confidence', 1.0) or 1.0),
                "embedding": emb,
            })

        smooth = self.smoother.update(confirmed_count)
        # attach smooth_count to every track so callers can use it
        for o in out:
            o["smooth_count"] = smooth

        return out
