"""Tes DETEKSI NAMA (pengenalan wajah) dari sumber video mana pun — CCTV (RTSP) atau webcam.

Berbeda dari test_rtsp.py (yang hanya mengecek koneksi & ukuran wajah), skrip ini
mencocokkan wajah yang terlihat ke galeri karyawan yang sudah di-enroll, lalu MENAMPILKAN
NAMANYA. Gunakan ini untuk memastikan CCTV benar-benar bisa mengenali orang SEBELUM
mengaktifkan absensi.

Sumber video mengikuti config (`camera.source`): default `config.yaml` = CCTV (rtsp).
Untuk uji webcam: tambahkan `--config config.testing.yaml`.

Cara pakai (virtualenv aktif, dari folder proyek):
    python scripts/test_recognize.py                    # CCTV live (jendela), tekan q keluar
    python scripts/test_recognize.py --detect-every 12  # live lebih mulus (deteksi tiap 12 frame)
    python scripts/test_recognize.py --no-show          # tanpa jendela: sampel beberapa frame, cetak nama
    python scripts/test_recognize.py --no-show --frames 15
    python scripts/test_recognize.py --config config.testing.yaml   # pakai webcam

Mode live menampilkan video TIAP frame (mulus) tapi menjalankan pengenalan hanya tiap
`--detect-every` frame; label nama terakhir digambar ulang di sela-selanya. Nama tetap
muncul otomatis — hanya di-refresh beberapa kali per detik, bukan tiap frame.

Warna kotak: hijau = dikenali (ada nama) | kuning = terdeteksi tapi tak dikenali |
             merah = wajah terlalu kecil (< min_face_width_px)
Kontrol jendela live: q = keluar, s = simpan snapshot ke data/reports/recognize_snap.jpg
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db  # noqa: E402
from src.camera import make_camera  # noqa: E402
from src.config import load_config  # noqa: E402
from src.recognizer import FaceRecognizer, build_recognizer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Tes deteksi nama via CCTV/webcam")
    ap.add_argument("--config", default=None, help="path config (default config.yaml = CCTV)")
    ap.add_argument("--no-show", action="store_true", help="tanpa jendela; sampel N frame lalu cetak nama")
    ap.add_argument("--frames", type=int, default=10, help="jumlah frame disampel di mode --no-show")
    ap.add_argument("--detect-every", type=int, default=8, dest="detect_every",
                    help="mode live: jalankan pengenalan tiap N frame (lebih besar = video lebih mulus, "
                         "label lebih jarang diperbarui). Default 8.")
    args = ap.parse_args()

    cfg = load_config(args.config)
    rec_cfg = cfg.recognition
    min_w = int(rec_cfg.get("min_face_width_px", 80))
    threshold = float(rec_cfg.get("match_threshold", 0.40))

    print(f"[i] Sumber : {cfg.camera.get('source')}", end="")
    if str(cfg.camera.get("source")).lower() == "rtsp":
        print(f"  ({cfg.rtsp_url(masked=True)})")
    else:
        print(f"  (webcam #{cfg.camera.get('webcam_index', 0)})")

    print("[i] Memuat model InsightFace...")
    recognizer = build_recognizer(cfg)

    db.init_db(cfg.db_path)
    with db.session(cfg.db_path) as conn:
        gallery, names, _ = db.load_gallery(conn)
    if gallery.shape[0] == 0:
        print("[!] Galeri kosong — jalankan 'python -m src.enroll' dulu agar nama bisa dikenali.")
    else:
        print(f"[i] Galeri: {gallery.shape[0]} embedding dari {len(set(names))} orang "
              f"({', '.join(sorted(set(names)))}).")

    out_dir = cfg.csv_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    def compute(frame):
        """Jalankan deteksi + pengenalan (bagian berat). Kembalikan:
        (daftar item gambar [x1,y1,x2,y2,color,label], daftar nama yang dikenali)."""
        items, recognized = [], []
        for f in recognizer.detect(frame):
            x1, y1, x2, y2 = f.bbox
            if f.width_px < min_w:
                color, label = (0, 0, 255), f"KECIL {f.width_px}px"
            else:
                name, score = FaceRecognizer.match(f.embedding, gallery, names, threshold)
                if name:
                    color, label = (0, 200, 0), f"{name} {score:.2f}"
                    recognized.append(name)
                else:
                    color, label = (0, 200, 255), f"? {score:.2f}"
            items.append((x1, y1, x2, y2, color, label))
        return items, recognized

    def draw(frame, items):
        """Gambar kotak & label (bagian ringan) — dipanggil tiap frame."""
        for (x1, y1, x2, y2, color, label) in items:
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(y1 - 8, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    # ---- Mode tanpa jendela: sampel beberapa frame, kumpulkan nama, simpan snapshot ----
    if args.no_show:
        with make_camera(cfg) as cam:
            seen: dict[str, int] = {}
            last_frame = None
            for n in range(1, args.frames + 1):
                frame = cam.read()
                if frame is None:
                    print(f"[x] Frame {n}: gagal mengambil frame dari kamera.")
                    continue
                items, recognized = compute(frame)
                for name in recognized:
                    seen[name] = seen.get(name, 0) + 1
                draw(frame, items)
                last_frame = frame
                time.sleep(0.5)
        if last_frame is not None:
            out = out_dir / "recognize_snap.jpg"
            cv2.imwrite(str(out), last_frame)
            print(f"[i] Snapshot terakhir disimpan: {out}")
        if seen:
            print("[✔] Nama yang dikenali (jumlah frame):")
            for name, cnt in sorted(seen.items(), key=lambda x: -x[1]):
                print(f"      - {name}: {cnt}x")
        else:
            print("[!] Tidak ada nama dikenali. Pastikan ada orang terdaftar di depan kamera, "
                  "wajah cukup besar & terang. Cek juga hasil test_rtsp.py (Fase 0).")
        return 0

    # ---- Mode live: video ditampilkan TIAP frame (mulus), pengenalan hanya tiap N frame ----
    detect_every = max(1, args.detect_every)
    print(f"[i] Jendela live terbuka (deteksi tiap {detect_every} frame). "
          f"Tekan 'q' untuk keluar, 's' untuk simpan snapshot.")
    with make_camera(cfg) as cam:
        try:
            i = 0
            last_items = []  # kotak & label terakhir; digambar ulang tiap frame
            while True:
                frame = cam.read()
                if frame is None:
                    continue
                if i % detect_every == 0:               # jalankan pengenalan sesekali
                    last_items, _ = compute(frame)
                i += 1
                draw(frame, last_items)                 # gambar label terakhir tiap frame
                cv2.imshow("Absenia — tes deteksi nama (q=keluar, s=simpan)", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("s"):
                    out = out_dir / "recognize_snap.jpg"
                    cv2.imwrite(str(out), frame)
                    print(f"[i] Snapshot disimpan: {out}")
        finally:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
