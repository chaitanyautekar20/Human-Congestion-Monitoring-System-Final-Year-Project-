import faiss
import numpy as np
import threading

class ReIDIndex:
    def __init__(self, dim=2048):
        self.dim = dim
        self.index = faiss.IndexFlatL2(dim)
        self.meta = []
        self.lock = threading.Lock()

    def add(self, emb, meta):
        if emb is None:
            return
        with self.lock:
            v = np.asarray(emb, dtype='float32').reshape(1, -1)
            self.index.add(v)
            self.meta.append(meta)

    def search(self, emb, top_k=20):
        if emb is None:
            return []
        q = np.asarray(emb, dtype='float32').reshape(1, -1)
        with self.lock:
            D, I = self.index.search(q, top_k)
            res = []
            for dist, idx in zip(D[0], I[0]):
                if idx < 0 or idx >= len(self.meta):
                    continue
                m = dict(self.meta[idx])
                m['distance'] = float(dist)
                res.append(m)
            return res
