"""State machine absensi harian.

Tanggung jawab:
- Menentukan sedang di FASE apa berdasarkan waktu sekarang: "in" (jendela pagi),
  "out" (jendela sore), atau None (di luar jendela / bukan hari kerja).
- Menerima daftar nama yang dikenali per frame, menerapkan aturan dedup
  (butuh >= min_detections deteksi sebelum dianggap sah), lalu mencatat ke DB:
    * clock_in  = deteksi sah PERTAMA di jendela pagi
    * clock_out = deteksi sah TERAKHIR di jendela sore

Counter deteksi disimpan di memori dan direset saat ganti hari. DB tetap jadi
sumber kebenaran final (aman bila proses restart di tengah jendela: clock_in
tidak akan tertimpa, clock_out selalu diperbarui ke yang terbaru).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, time

from . import db

log = logging.getLogger("absenia.attendance")

PHASE_IN = "in"
PHASE_OUT = "out"


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


class AttendanceTracker:
    def __init__(self, cfg) -> None:
        att = cfg.attendance
        self.db_path = cfg.db_path
        self.min_detections = int(att.get("min_detections", 3))
        self.workdays = set(att.get("workdays", [0, 1, 2, 3, 4]))
        ci = att.get("clock_in_window", {})
        co = att.get("clock_out_window", {})
        self.in_start = _parse_hhmm(ci.get("start", "07:45"))
        self.in_end = _parse_hhmm(ci.get("end", "09:00"))
        self.out_start = _parse_hhmm(co.get("start", "16:30"))
        self.out_end = _parse_hhmm(co.get("end", "18:00"))

        # counter[(phase, name)] -> jumlah deteksi hari ini
        self._counts: dict[tuple[str, str], int] = defaultdict(int)
        # nama yang sudah di-commit clock_in agar tak diproses berulang
        self._committed_in: set[str] = set()
        self._current_day: date | None = None

        db.init_db(self.db_path)

    # ---------- penentuan fase ----------
    def phase_at(self, now: datetime) -> str | None:
        if now.weekday() not in self.workdays:
            return None
        t = now.time()
        if self.in_start <= t <= self.in_end:
            return PHASE_IN
        if self.out_start <= t <= self.out_end:
            return PHASE_OUT
        return None

    def _roll_day_if_needed(self, today: date) -> None:
        if self._current_day != today:
            self._current_day = today
            self._counts.clear()
            self._committed_in.clear()
            log.info("Hari baru %s — counter direset.", today.isoformat())

    # ---------- pemrosesan ----------
    def process(self, recognized_names: list[str], now: datetime) -> list[str]:
        """Proses nama-nama yang dikenali di SATU frame untuk fase saat ini.

        Returns daftar pesan event (untuk log/tampilan). Nama duplikat dalam satu
        frame dihitung sekali (pakai set) agar 1 frame = maksimal 1 deteksi/orang.
        """
        phase = self.phase_at(now)
        if phase is None:
            return []

        today = now.date()
        self._roll_day_if_needed(today)
        work_date = today.isoformat()
        ts = now.strftime("%H:%M:%S")
        events: list[str] = []

        for name in set(recognized_names):
            key = (phase, name)
            self._counts[key] += 1
            n = self._counts[key]

            if phase == PHASE_IN:
                # Commit clock_in sekali saja, setelah cukup deteksi.
                if n == self.min_detections and name not in self._committed_in:
                    with db.session(self.db_path) as conn:
                        db.record_clock_in(conn, work_date, self._emp_id(conn, name), ts)
                    self._committed_in.add(name)
                    events.append(f"CLOCK-IN  {name} @ {ts}")
                    log.info("Clock-in %s @ %s", name, ts)

            else:  # PHASE_OUT
                # Setelah cukup deteksi, terus perbarui clock_out ke ts terbaru.
                if n >= self.min_detections:
                    with db.session(self.db_path) as conn:
                        db.record_clock_out(conn, work_date, self._emp_id(conn, name), ts)
                    # log hanya saat pertama kali melewati ambang, agar tidak spam
                    if n == self.min_detections:
                        events.append(f"CLOCK-OUT {name} @ {ts} (akan di-update ke terakhir)")
                        log.info("Clock-out awal %s @ %s", name, ts)

        return events

    def _emp_id(self, conn, name: str) -> int:
        return db.upsert_employee(conn, name)
