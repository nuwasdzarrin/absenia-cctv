"""Absenia — sistem absensi CCTV via face recognition."""

# Paksa output console ke UTF-8 agar simbol seperti ✔ tidak error di Windows (cp1252).
import sys as _sys

for _stream in ("stdout", "stderr"):
    try:
        getattr(_sys, _stream).reconfigure(encoding="utf-8")
    except Exception:
        pass
