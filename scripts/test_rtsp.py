"""FASE 0 — Proof of Concept (jalankan ini PALING PERTAMA).

Tujuan: buktikan bahwa
  1. PC bisa menarik stream RTSP dari kamera Tapo Anda, dan
  2. wajah di ruangan itu benar-benar terdeteksi dengan ukuran yang MEMADAI
     untuk face recognition (lebar >= min_face_width_px di config).

Cara pakai (dari folder root proyek, virtualenv aktif):
    python scripts/test_rtsp.py            # ambil 1 frame, deteksi, simpan hasil
    python scripts/test_rtsp.py --show     # tampilkan jendela live (butuh layar/GUI)
    python scripts/test_rtsp.py --frames 5 # ambil 5 frame berturut

Output disimpan ke data/reports/poc_*.jpg dengan kotak wajah tergambar + ukuran pixel.
Jika wajah tidak terdeteksi / terlalu kecil (< min_face_width_px), setel ulang posisi
atau resolusi kamera SEBELUM lanjut ke fase berikutnya.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.camera import RtspCamera  # noqa: E402
from src.config import load_config  # noqa: E402
from src.recognizer import FaceRecognizer  # noqa: E402


def draw_faces(frame, faces, min_w: int):
    for i, f in enumerate(faces, 1):
        x1, y1, x2, y2 = f.bbox
        ok = f.width_px >= min_w
        color = (0, 200, 0) if ok else (0, 0, 255)  # hijau=layak, merah=terlalu kecil
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"#{i} {f.width_px}px {'OK' if ok else 'KECIL'}"
        cv2.putText(frame, label, (x1, max(y1 - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return frame


def main() -> int:
    ap = argparse.ArgumentParser(description="PoC RTSP + deteksi wajah")
    ap.add_argument("--frames", type=int, default=1, help="berapa frame diambil")
    ap.add_argument("--show", action="store_true", help="tampilkan jendela live")
    args = ap.parse_args()

    cfg = load_config()
    rec_cfg = cfg.recognition
    min_w = int(rec_cfg.get("min_face_width_px", 80))

    print(f"[i] RTSP  : {cfg.rtsp_url(masked=True)}")
    print(f"[i] Model : InsightFace buffalo_l (GPU={rec_cfg.get('use_gpu', False)})")
    print("[i] Memuat model (unduhan pertama bisa beberapa menit)...")

    recognizer = FaceRecognizer(
        det_size=tuple(rec_cfg.get("det_size", [640, 640])),
        use_gpu=bool(rec_cfg.get("use_gpu", False)),
        min_face_width_px=min_w,
    )

    out_dir = cfg.csv_dir  # reuse folder reports untuk simpan gambar PoC
    out_dir.mkdir(parents=True, exist_ok=True)

    ok_any = False
    with RtspCamera(cfg.rtsp_url(), cfg.rtsp_url(masked=True),
                    int(cfg.camera.get("reconnect_delay_sec", 5))) as cam:
        for n in range(1, args.frames + 1):
            frame = cam.read()
            if frame is None:
                print(f"[x] Frame {n}: GAGAL mengambil frame. Cek IP/kredensial/jaringan.")
                continue
            h, w = frame.shape[:2]
            faces = recognizer.detect(frame)
            usable = [f for f in faces if f.width_px >= min_w]
            print(f"[i] Frame {n}: resolusi {w}x{h}, {len(faces)} wajah terdeteksi, "
                  f"{len(usable)} layak (>= {min_w}px).")
            for f in faces:
                print(f"      - wajah {f.width_px}px  det_score={f.det_score:.2f}")

            draw_faces(frame, faces, min_w)
            out_path = out_dir / f"poc_{n:02d}.jpg"
            cv2.imwrite(str(out_path), frame)
            print(f"[i] Disimpan: {out_path}")
            if usable:
                ok_any = True

            if args.show:
                cv2.imshow("Absenia PoC (tekan q untuk keluar)", frame)
                if cv2.waitKey(1500) & 0xFF == ord("q"):
                    break

    if args.show:
        cv2.destroyAllWindows()

    print()
    if ok_any:
        print("[✔] LULUS Fase 0: ada wajah dengan ukuran memadai. Lanjut ke enrollment.")
        return 0
    print("[!] BELUM lulus: tidak ada wajah layak. Perbaiki posisi/resolusi kamera dulu.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
