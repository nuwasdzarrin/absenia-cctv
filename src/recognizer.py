"""Pembungkus InsightFace: deteksi wajah + embedding + pencocokan.

Satu kelas `FaceRecognizer`:
- detect(frame) -> daftar wajah (bbox, embedding ternormalisasi, ukuran)
- match(embedding, gallery) -> (nama, skor) terbaik atau (None, skor) bila di bawah threshold

Model buffalo_l menghasilkan embedding 512-dim. Diunduh otomatis oleh insightface
saat pertama kali dijalankan (butuh internet sekali).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class DetectedFace:
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    embedding: np.ndarray            # 512-dim, sudah dinormalisasi L2
    width_px: int
    det_score: float                 # kepercayaan detektor (bukan skor kecocokan identitas)


class FaceRecognizer:
    def __init__(
        self,
        model_name: str = "buffalo_l",
        det_size: tuple[int, int] = (640, 640),
        use_gpu: bool = False,
        min_face_width_px: int = 80,
    ) -> None:
        # Import di dalam __init__ supaya modul lain (mis. test config) bisa di-import
        # tanpa harus punya insightface terpasang.
        from insightface.app import FaceAnalysis

        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if use_gpu
            else ["CPUExecutionProvider"]
        )
        # buffalo_l = akurat (default). buffalo_s = ringan, cocok untuk SoC/ARM (mis. HG680P).
        self.app = FaceAnalysis(name=model_name, providers=providers)
        ctx_id = 0 if use_gpu else -1
        self.app.prepare(ctx_id=ctx_id, det_size=det_size)
        self.min_face_width_px = min_face_width_px

    def detect(self, frame_bgr: np.ndarray) -> list[DetectedFace]:
        """Deteksi semua wajah pada frame BGR (format OpenCV). Filter wajah terlalu kecil."""
        faces = self.app.get(frame_bgr)
        results: list[DetectedFace] = []
        for f in faces:
            x1, y1, x2, y2 = (int(v) for v in f.bbox)
            width = x2 - x1
            if width < self.min_face_width_px:
                continue
            emb = np.asarray(f.normed_embedding, dtype=np.float32)  # sudah L2-normalized
            results.append(
                DetectedFace(
                    bbox=(x1, y1, x2, y2),
                    embedding=emb,
                    width_px=width,
                    det_score=float(f.det_score),
                )
            )
        return results

    @staticmethod
    def match(
        embedding: np.ndarray,
        gallery: np.ndarray,
        names: list[str],
        threshold: float,
    ) -> tuple[str | None, float]:
        """Cocokkan satu embedding ke galeri (matrix N x 512 ternormalisasi).

        Returns (nama, skor) bila skor terbaik >= threshold, selain itu (None, skor).
        Karena semua vektor ternormalisasi, dot product == cosine similarity.
        """
        if gallery.shape[0] == 0:
            return None, 0.0
        sims = gallery @ embedding  # [N]
        best_idx = int(np.argmax(sims))
        best_score = float(sims[best_idx])
        if best_score >= threshold:
            return names[best_idx], best_score
        return None, best_score


def build_recognizer(cfg) -> "FaceRecognizer":
    """Buat FaceRecognizer dari config (dipakai semua modul agar setelan konsisten)."""
    rc = cfg.recognition
    return FaceRecognizer(
        model_name=str(rc.get("model_name", "buffalo_l")),
        det_size=tuple(rc.get("det_size", [640, 640])),
        use_gpu=bool(rc.get("use_gpu", False)),
        min_face_width_px=int(rc.get("min_face_width_px", 80)),
    )
