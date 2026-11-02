import os
from dotenv import load_dotenv
load_dotenv()

YOLO_MODEL_PATH = os.getenv("YOLO_MODEL_PATH", "models/yolov8n.pt")
DB_PATH = os.getenv("DB_PATH", "crowdwatch.db")
# tuning
PROCESS_FPS = int(os.getenv("PROCESS_FPS", "5"))           # frames per second to process
BROADCAST_STATS_INTERVAL = float(os.getenv("BROADCAST_STATS_INTERVAL", "1.0"))  # broadcast every 1s for snappier UI
