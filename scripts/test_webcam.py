"""UJI COBA VIA WEBCAM — jalankan ini untuk mencoba sistem tanpa CCTV.

Membuka webcam laptop/PC, mendeteksi wajah secara live, dan (bila sudah enroll)
menampilkan NAMA + skor kecocokan. Ini cara termudah menguji seluruh pipeline
pengenalan wajah sebelum menyambung ke CCTV Tapo.

Cara pakai (dari folder root proyek, virtualenv aktif):
    python scripts/test_webcam.py            # webcam default (index 0), live preview
    python scripts/test_webcam.py --index 1  # pilih webcam lain
    python scripts/test_webcam.py --no-show  # tanpa jendela, ambil 1 frame lalu simpan

Kontrol saat jendela live terbuka:
    q  = keluar
    s  = simpan snapshot ke data/reports/webcam_snap.jpg

Warna kotak:
    hijau  = wajah dikenali (ada namanya)
    kuning = wajah terdeteksi tapi tidak dikenali / belum enroll
    merah  = wajah terlalu kecil (< min_face_width_px)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.camera import WebcamCamera  # noqa: E402
from src.config import load_config  # noqa: E402
from src.recognizer import FaceRecognizer, build_recognizer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Uji deteksi & pengenalan wajah via webcam")
    ap.add_argument("--index", type=int, default=None, help="index webcam (default dari config)")
    ap.add_argument("--no-show", action="store_true", help="tanpa jendela; ambil 1 frame lalu simpan")
    args = ap.parse_args()

    cfg = load_config()
    rec_cfg = cfg.recognition
    min_w = int(rec_cfg.get("min_face_width_px", 80))
    threshold = float(rec_cfg.get("match_threshold", 0.40))
    index = args.index if args.index is not None else int(cfg.camera.get("webcam_index", 0))

    print("[i] Memuat model InsightFace (unduhan pertama bisa beberapa menit)...")
    recognizer = build_recognizer(cfg)

    # muat galeri wajah bila sudah ada yang di-enroll (opsional)
    db.init_db(cfg.db_path)
    with db.session(cfg.db_path) as conn:
        gallery, names, _ = db.load_gallery(conn)
    if gallery.shape[0] == 0:
        print("[i] Galeri kosong — hanya deteksi wajah (belum bisa tampilkan nama).")
        print("    Jalankan 'python -m src.enroll' dulu untuk menguji pengenalan nama.")
    else:
        print(f"[i] Galeri: {gallery.shape[0]} embedding dari {len(set(names))} orang.")

    out_dir = cfg.csv_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    def annotate(frame):
        for f in recognizer.detect(frame):
            x1, y1, x2, y2 = f.bbox
            if f.width_px < min_w:
                color, label = (0, 0, 255), f"KECIL {f.width_px}px"
            else:
                name, score = FaceRecognizer.match(f.embedding, gallery, names, threshold)
                if name:
                    color, label = (0, 200, 0), f"{name} {score:.2f}"
                else:
                    color, label = (0, 200, 255), f"? {score:.2f}"
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(y1 - 8, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        return frame

    cam = WebcamCamera(index)
    if not cam.open():
        print(f"[x] Tidak bisa membuka webcam index {index}. Coba --index 1.")
        return 1

    if args.no_show:
        # Warm-up: webcam (DirectShow) sering memberi frame kosong di awal sampai
        # auto-exposure aktif. Buang beberapa frame + jeda singkat, pakai yang terakhir.
        frame = None
        for _ in range(20):
            frame = cam.read()
            time.sleep(0.1)
        cam.release()
        if frame is None:
            print("[x] Gagal mengambil frame dari webcam.")
            return 1
        faces = recognizer.detect(frame)
        print(f"[i] {len(faces)} wajah terdeteksi pada frame.")
        annotate(frame)
        out = out_dir / "webcam_snap.jpg"
        cv2.imwrite(str(out), frame)
        print(f"[i] Snapshot disimpan: {out}")
        return 0

    print("[i] Jendela live terbuka. Tekan 'q' untuk keluar, 's' untuk simpan snapshot.")
    try:
        while True:
            frame = cam.read()
            if frame is None:
                continue
            annotate(frame)
            cv2.imshow("Absenia — uji webcam (q=keluar, s=simpan)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                out = out_dir / "webcam_snap.jpg"
                cv2.imwrite(str(out), frame)
                print(f"[i] Snapshot disimpan: {out}")
    finally:
        cam.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
