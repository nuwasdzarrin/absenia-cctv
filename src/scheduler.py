"""Loop utama berbasis jendela waktu.

Alih-alih memproses video 24 jam, loop ini hanya "sibuk" saat berada di dalam
jendela pagi/sore. Di luar jendela ia tidur lebih lama (hemat CPU & listrik).

Transisi fase dipantau: begitu KELUAR dari sebuah jendela (mis. jam lewat 09:00
atau 18:00), rekap hari itu diekspor ke CSV + Google Sheet.

Galeri wajah (embedding karyawan) dimuat ulang setiap kali MASUK jendela baru,
sehingga karyawan yang baru di-enroll langsung dikenali tanpa restart.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from . import db, sheets
from .attendance import AttendanceTracker
from .camera import BaseCamera, make_camera
from .config import Config
from .recognizer import FaceRecognizer

log = logging.getLogger("absenia.scheduler")


def _now() -> datetime:
    # Dipisah agar mudah di-monkeypatch saat testing/simulasi.
    return datetime.now()


class WindowRunner:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.tracker = AttendanceTracker(cfg)
        self.recognizer = FaceRecognizer(
            det_size=tuple(cfg.recognition.get("det_size", [640, 640])),
            use_gpu=bool(cfg.recognition.get("use_gpu", False)),
            min_face_width_px=int(cfg.recognition.get("min_face_width_px", 80)),
        )
        self.threshold = float(cfg.recognition.get("match_threshold", 0.40))
        self.sample_interval = int(cfg.camera.get("sample_interval_sec", 3))
        self.idle_sleep = 20  # detik tidur saat di luar jendela

        # galeri wajah
        self._gallery = None
        self._names: list[str] = []
        self._reload_gallery()

    def _reload_gallery(self) -> None:
        with db.session(self.cfg.db_path) as conn:
            gallery, names, _ = db.load_gallery(conn)
        self._gallery, self._names = gallery, names
        log.info("Galeri dimuat: %d embedding dari %d wajah unik.",
                 gallery.shape[0], len(set(names)))
        if gallery.shape[0] == 0:
            log.warning("Galeri KOSONG — jalankan enrollment dulu (python -m src.enroll).")

    def _recognize_frame(self, frame) -> list[str]:
        names: list[str] = []
        for face in self.recognizer.detect(frame):
            name, score = FaceRecognizer.match(
                face.embedding, self._gallery, self._names, self.threshold
            )
            if name is not None:
                names.append(name)
        return names

    def run(self, duration_sec: float | None = None) -> None:
        """Loop utama. Bila duration_sec diisi, berhenti setelah sekian detik
        (dipakai untuk uji coba supaya tidak berjalan selamanya)."""
        log.info("Absenia mulai. Menunggu jendela absensi...")
        prev_phase: str | None = None
        cam: BaseCamera | None = None
        started = time.monotonic()

        while True:
            if duration_sec is not None and (time.monotonic() - started) >= duration_sec:
                log.info("Durasi uji (%.0f dtk) tercapai, berhenti.", duration_sec)
                if cam is not None:
                    cam.release()
                # Ekspor rekap hari ini agar hasil uji ikut terkirim ke Sheet
                # (mode --seconds berhenti di tengah jendela, jadi ekspor akhir-jendela
                # tidak sempat jalan; ini menutup celah itu).
                sheets.export_day(self.cfg, _now().date().isoformat())
                break

            now = _now()
            phase = self.tracker.phase_at(now)

            # --- transisi MASUK jendela ---
            if phase and prev_phase is None:
                log.info("Masuk jendela '%s' pada %s.", phase, now.strftime("%H:%M:%S"))
                self._reload_gallery()
                cam = make_camera(self.cfg)
                cam.open()

            # --- di dalam jendela: sampling & proses ---
            if phase:
                if cam is not None:
                    frame = cam.read()
                    if frame is not None:
                        names = self._recognize_frame(frame)
                        for ev in self.tracker.process(names, now):
                            log.info("EVENT: %s", ev)
                prev_phase = phase
                time.sleep(self.sample_interval)
                continue

            # --- transisi KELUAR jendela: ekspor rekap ---
            if prev_phase is not None:
                log.info("Keluar jendela '%s'. Mengekspor rekap...", prev_phase)
                if cam is not None:
                    cam.release()
                    cam = None
                sheets.export_day(self.cfg, now.date().isoformat())
                prev_phase = None

            time.sleep(self.idle_sleep)
