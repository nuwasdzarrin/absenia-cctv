"""Ekspor rekap absensi harian ke Google Sheet lewat **Google Apps Script Web App**,
plus backup CSV lokal.

Kenapa Apps Script (bukan service account)? Jauh lebih sederhana untuk non-developer:
tidak perlu file kredensial JSON. Cukup deploy skrip di apps_script/Code.gs sebagai
Web App, salin URL-nya ke .env, selesai. PC hanya mengirim HTTP POST berisi data.

Alur:
    DB  ->  susun baris harian  ->  tulis CSV (selalu)  ->  POST JSON ke Apps Script

Payload POST:
    {
      "token": "<APPS_SCRIPT_TOKEN>",
      "worksheet": "Absensi",
      "rows": [ {tanggal, nama, jam_masuk, jam_pulang, status, deteksi_masuk, deteksi_pulang}, ... ]
    }
Apps Script melakukan upsert berdasarkan (tanggal, nama).
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import date

from . import db

log = logging.getLogger("absenia.sheets")

HEADER = ["Tanggal", "Nama", "Jam Masuk", "Jam Pulang", "Status"]


def _status(clock_in: str | None, clock_out: str | None) -> str:
    if clock_in and clock_out:
        return "Hadir"
    if clock_in and not clock_out:
        return "Tidak clock-out"
    if not clock_in and clock_out:
        return "Tidak clock-in"
    return "Tidak hadir"


def _rows_for_day(cfg, work_date: str) -> list[dict]:
    with db.session(cfg.db_path) as conn:
        recs = db.get_day_attendance(conn, work_date)
    rows = []
    for r in recs:
        rows.append({
            "tanggal": work_date,
            "nama": r["name"],
            "jam_masuk": r["clock_in"] or "",
            "jam_pulang": r["clock_out"] or "",
            "status": _status(r["clock_in"], r["clock_out"]),
        })
    return rows


def write_csv(cfg, work_date: str) -> str:
    """Tulis/timpa CSV harian. Returns path file."""
    cfg.csv_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.csv_dir / f"absensi_{work_date}.csv"
    rows = _rows_for_day(cfg, work_date)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r["tanggal"], r["nama"], r["jam_masuk"], r["jam_pulang"],
                        r["status"]])
    log.info("CSV harian ditulis: %s (%d baris)", out, len(rows))
    return str(out)


def sync_to_sheet(cfg, work_date: str) -> None:
    """Kirim baris hari `work_date` ke Apps Script Web App. Tidak fatal bila gagal."""
    if not cfg.sheets.get("enabled", False):
        log.info("Google Sheet dinonaktifkan (sheets.enabled=false), lewati.")
        return
    rows = _rows_for_day(cfg, work_date)
    if not rows:
        log.info("Tidak ada data untuk %s, tidak ada yang dikirim.", work_date)
        return

    url = cfg.apps_script_url()
    payload = {
        "token": cfg.apps_script_token() or "",
        "worksheet": cfg.sheets.get("worksheet_name", "Absensi"),
        "rows": rows,
    }
    try:
        import requests

        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {"raw": resp.text[:200]}
        if isinstance(body, dict) and body.get("ok") is False:
            log.error("Apps Script menolak data: %s (data aman di CSV & DB).",
                      body.get("error"))
        else:
            log.info("Terkirim ke Google Sheet via Apps Script: %d baris (%s).",
                     len(rows), body)
    except Exception as e:  # noqa: BLE001 — jangan jatuhkan sistem karena gagal kirim
        log.error("Gagal kirim ke Apps Script: %s (data aman di CSV & DB).", e)


def export_day(cfg, work_date: str | None = None) -> None:
    """Ekspor lengkap satu hari: CSV backup + kirim ke Google Sheet."""
    if work_date is None:
        work_date = date.today().isoformat()
    write_csv(cfg, work_date)
    sync_to_sheet(cfg, work_date)
