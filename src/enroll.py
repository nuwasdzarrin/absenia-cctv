"""FASE 1 — Enrollment karyawan.

Baca folder data/faces/<nama>/*.jpg, hitung embedding tiap foto, simpan ke SQLite.
Struktur folder = sumber kebenaran nama karyawan:

    data/faces/
        budi/   1.jpg 2.jpg 3.jpg
        siti/   a.jpg b.jpg

Aturan:
- Tiap foto sebaiknya berisi TEPAT SATU wajah (foto potret). Bila terdeteksi >1 wajah,
  dipakai wajah terbesar dan diberi peringatan.
- Embedding lama karyawan yang di-enroll ulang akan diganti (clear lalu isi baru).

Cara pakai:
    python -m src.enroll                 # enroll semua orang di data/faces
    python -m src.enroll --name budi     # enroll ulang satu orang saja
    python -m src.enroll --list          # tampilkan siapa saja yang sudah terdaftar
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from . import db
from .config import load_config
from .recognizer import FaceRecognizer, build_recognizer

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _largest_face(faces):
    return max(faces, key=lambda f: f.width_px) if faces else None


def enroll_person(conn, recognizer: FaceRecognizer, person_dir: Path) -> int:
    name = person_dir.name
    images = [p for p in sorted(person_dir.iterdir()) if p.suffix.lower() in IMG_EXT]
    if not images:
        print(f"[!] {name}: tidak ada foto, dilewati.")
        return 0

    emp_id = db.upsert_employee(conn, name)
    db.clear_embeddings_for(conn, emp_id)  # enroll ulang bersih

    count = 0
    for img_path in images:
        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"[!] {name}: gagal baca {img_path.name}, dilewati.")
            continue
        faces = recognizer.detect(frame)
        if not faces:
            print(f"[!] {name}: tidak ada wajah terdeteksi di {img_path.name}.")
            continue
        if len(faces) > 1:
            print(f"[!] {name}: {len(faces)} wajah di {img_path.name}, pakai yang terbesar.")
        face = _largest_face(faces)
        db.add_embedding(conn, emp_id, face.embedding, source=img_path.name)
        count += 1
        print(f"[+] {name}: {img_path.name} (wajah {face.width_px}px) tersimpan.")

    print(f"[=] {name}: {count} embedding tersimpan.\n")
    return count


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrollment wajah karyawan")
    ap.add_argument("--name", help="enroll ulang satu orang (nama subfolder)")
    ap.add_argument("--list", action="store_true", help="tampilkan karyawan terdaftar")
    ap.add_argument("--config", default=None,
                    help="path file config (mis. config.lowpower.yaml untuk model buffalo_s)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    db.init_db(cfg.db_path)

    if args.list:
        with db.session(cfg.db_path) as conn:
            rows = db.list_employees(conn)
            if not rows:
                print("Belum ada karyawan terdaftar.")
            for r in rows:
                print(f"  - {r['name']}  ({r['n_emb']} embedding)")
        return 0

    faces_dir = cfg.faces_dir
    if not faces_dir.exists():
        print(f"[x] Folder foto tidak ada: {faces_dir}")
        return 1

    print("[i] Memuat model InsightFace...")
    recognizer = build_recognizer(cfg)

    if args.name:
        person_dirs = [faces_dir / args.name]
        if not person_dirs[0].is_dir():
            print(f"[x] Folder tidak ada: {person_dirs[0]}")
            return 1
    else:
        person_dirs = [p for p in sorted(faces_dir.iterdir()) if p.is_dir()]

    if not person_dirs:
        print(f"[x] Tidak ada subfolder karyawan di {faces_dir}. "
              f"Buat data/faces/<nama>/ lalu isi fotonya.")
        return 1

    total = 0
    with db.session(cfg.db_path) as conn:
        for pdir in person_dirs:
            total += enroll_person(conn, recognizer, pdir)

    print(f"[✔] Selesai. Total {total} embedding dari {len(person_dirs)} orang.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
