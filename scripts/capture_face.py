"""Ambil foto wajah untuk enrollment langsung dari webcam.

Menyimpan beberapa foto ke data/faces/<nama>/ secara otomatis — hanya frame yang
berisi TEPAT SATU wajah cukup besar yang disimpan. Hadapkan wajah ke kamera saat
skrip berjalan (variasikan sedikit sudut/ekspresi).

Cara pakai:
    python scripts/capture_face.py --name nuwas            # ambil 5 foto (default)
    python scripts/capture_face.py --name budi --count 6   # ambil 6 foto
    python scripts/capture_face.py --name siti --index 1   # webcam lain
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.camera import WebcamCamera  # noqa: E402
from src.config import load_config  # noqa: E402
from src.recognizer import FaceRecognizer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Ambil foto enrollment via webcam")
    ap.add_argument("--name", required=True, help="nama karyawan (jadi nama subfolder)")
    ap.add_argument("--count", type=int, default=5, help="jumlah foto yang diambil")
    ap.add_argument("--index", type=int, default=None, help="index webcam")
    args = ap.parse_args()

    cfg = load_config()
    rec_cfg = cfg.recognition
    min_w = int(rec_cfg.get("min_face_width_px", 80))
    index = args.index if args.index is not None else int(cfg.camera.get("webcam_index", 0))

    out_dir = cfg.faces_dir / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[i] Memuat model InsightFace...")
    recognizer = FaceRecognizer(
        det_size=tuple(rec_cfg.get("det_size", [640, 640])),
        use_gpu=bool(rec_cfg.get("use_gpu", False)),
        min_face_width_px=min_w,
    )

    cam = WebcamCamera(index)
    if not cam.open():
        print(f"[x] Tidak bisa membuka webcam index {index}.")
        return 1

    print("[i] Hadapkan wajah ke kamera. Mengambil foto...")
    saved = 0
    attempts = 0
    max_attempts = 300  # ~30 detik pada 0.1s/loop
    try:
        while saved < args.count and attempts < max_attempts:
            attempts += 1
            frame = cam.read()
            if frame is None:
                continue
            faces = recognizer.detect(frame)
            # butuh tepat satu wajah cukup besar agar foto enrollment bersih
            if len(faces) == 1 and faces[0].width_px >= min_w:
                saved += 1
                path = out_dir / f"{saved}.jpg"
                cv2.imwrite(str(path), frame)
                print(f"[+] Foto {saved}/{args.count} tersimpan: {path} "
                      f"(wajah {faces[0].width_px}px)")
                time.sleep(0.6)  # jeda agar antar-foto sedikit berbeda
            else:
                time.sleep(0.1)
    finally:
        cam.release()

    if saved == 0:
        print("[x] Tidak ada wajah tertangkap. Pastikan wajah menghadap & cukup dekat "
              "ke kamera, pencahayaan cukup, lalu ulangi.")
        return 1
    print(f"[✔] Selesai: {saved} foto di {out_dir}. Lanjutkan dengan 'python -m src.enroll'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
