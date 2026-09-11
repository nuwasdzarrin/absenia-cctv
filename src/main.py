"""Entry point Absenia.

Perintah:
    python -m src.main run        # jalankan loop absensi (mode produksi, long-running)
    python -m src.main export     # ekspor rekap hari ini ke CSV + Google Sheet (manual)
    python -m src.main export --date 2026-09-11
    python -m src.main status     # tampilkan rekap hari ini di terminal

Dipakai bersama Windows Task Scheduler (trigger "At log on") untuk auto-start.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from . import db, sheets
from .config import load_config
from .scheduler import WindowRunner


def _setup_logging(cfg) -> None:
    level = getattr(logging, str(cfg.logging_cfg.get("level", "INFO")).upper(), logging.INFO)
    log_file = cfg._abs(cfg.logging_cfg.get("file", "data/absenia.log"))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def cmd_run(cfg, seconds: float | None = None) -> int:
    runner = WindowRunner(cfg)
    try:
        runner.run(duration_sec=seconds)
    except KeyboardInterrupt:
        logging.getLogger("absenia").info("Dihentikan oleh pengguna (Ctrl+C).")
    return 0


def cmd_export(cfg, work_date: str | None) -> int:
    sheets.export_day(cfg, work_date or date.today().isoformat())
    return 0


def cmd_status(cfg, work_date: str | None) -> int:
    wd = work_date or date.today().isoformat()
    with db.session(cfg.db_path) as conn:
        rows = db.get_day_attendance(conn, wd)
    print(f"\nRekap absensi {wd}:")
    print(f"{'Nama':<20} {'Masuk':<10} {'Pulang':<10} {'Status'}")
    print("-" * 55)
    if not rows:
        print("(belum ada data)")
    for r in rows:
        status = ("Hadir" if r["clock_in"] and r["clock_out"]
                  else "Tidak clock-out" if r["clock_in"]
                  else "Tidak clock-in" if r["clock_out"] else "-")
        print(f"{r['name']:<20} {r['clock_in'] or '-':<10} "
              f"{r['clock_out'] or '-':<10} {status}")
    print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="absenia", description="Sistem absensi CCTV")
    # Flag --config dipakai bersama semua subcommand (parent parser).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=None,
                        help="path file config (default config.yaml; mis. config.testing.yaml)")
    sub = ap.add_subparsers(dest="command", required=True)
    pr = sub.add_parser("run", parents=[common], help="jalankan loop absensi")
    pr.add_argument("--seconds", type=float, default=None,
                    help="berhenti otomatis setelah sekian detik (untuk uji coba)")
    pe = sub.add_parser("export", parents=[common], help="ekspor rekap ke CSV + Google Sheet")
    pe.add_argument("--date", help="tanggal YYYY-MM-DD (default hari ini)")
    ps = sub.add_parser("status", parents=[common], help="tampilkan rekap di terminal")
    ps.add_argument("--date", help="tanggal YYYY-MM-DD (default hari ini)")
    args = ap.parse_args()

    cfg = load_config(getattr(args, "config", None))
    _setup_logging(cfg)

    if args.command == "run":
        return cmd_run(cfg, getattr(args, "seconds", None))
    if args.command == "export":
        return cmd_export(cfg, getattr(args, "date", None))
    if args.command == "status":
        return cmd_status(cfg, getattr(args, "date", None))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
