"""Loader konfigurasi: gabungkan config.yaml (non-rahasia) + .env (rahasia).

Menyediakan satu objek `Config` yang dipakai semua modul, plus helper untuk
menyusun URL RTSP dari kredensial di .env.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Root proyek = folder di atas src/
ROOT = Path(__file__).resolve().parent.parent


def _mask_url_credentials(url: str) -> str:
    """Sembunyikan password dalam URL untuk log: ://user:pass@ -> ://user:****@"""
    return re.sub(r"://([^:/@]+):([^@/]+)@", r"://\1:****@", url)


def _get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(
            f"Environment variable '{name}' belum di-set. "
            f"Salin .env.example menjadi .env lalu isi nilainya."
        )
    return val


@dataclass
class Config:
    raw: dict[str, Any] = field(default_factory=dict)

    # -- akses cepat sub-bagian --
    @property
    def camera(self) -> dict[str, Any]:
        return self.raw.get("camera", {})

    @property
    def recognition(self) -> dict[str, Any]:
        return self.raw.get("recognition", {})

    @property
    def attendance(self) -> dict[str, Any]:
        return self.raw.get("attendance", {})

    @property
    def storage(self) -> dict[str, Any]:
        return self.raw.get("storage", {})

    @property
    def sheets(self) -> dict[str, Any]:
        return self.raw.get("sheets", {})

    @property
    def logging_cfg(self) -> dict[str, Any]:
        return self.raw.get("logging", {})

    # -- path yang sudah di-resolve ke absolut --
    def path(self, key_chain: str) -> Path:
        """Ambil path relatif dari config dan jadikan absolut terhadap ROOT."""
        node: Any = self.raw
        for k in key_chain.split("."):
            node = node[k]
        p = Path(node)
        return p if p.is_absolute() else (ROOT / p)

    @property
    def db_path(self) -> Path:
        return self._abs(self.storage.get("db_path", "data/absenia.db"))

    @property
    def faces_dir(self) -> Path:
        return self._abs(self.storage.get("faces_dir", "data/faces"))

    @property
    def csv_dir(self) -> Path:
        return self._abs(self.storage.get("csv_dir", "data/reports"))

    def _abs(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (ROOT / p)

    # -- kredensial dari .env --
    def rtsp_url(self, masked: bool = False) -> str:
        """Susun URL RTSP dari .env + config. masked=True menyembunyikan password (untuk log)."""
        user = _get_env("TAPO_RTSP_USER", required=True)
        password = _get_env("TAPO_RTSP_PASS", required=True)
        ip = _get_env("TAPO_IP", required=True)
        port = self.camera.get("rtsp_port", 554)
        stream = self.camera.get("rtsp_path", "stream1")
        shown_pass = "****" if masked else password
        return f"rtsp://{user}:{shown_pass}@{ip}:{port}/{stream}"

    def stream_url(self, masked: bool = False) -> str:
        """URL stream generik dari .env (STREAM_URL) — untuk HP jadi IP camera,
        atau kamera merek lain (RTSP/MJPEG). Dipakai bila camera.source = "url"."""
        url = _get_env("STREAM_URL", required=True)
        return _mask_url_credentials(url) if masked else url

    def apps_script_url(self) -> str:
        return _get_env("APPS_SCRIPT_URL", required=True)

    def apps_script_token(self) -> str | None:
        return _get_env("APPS_SCRIPT_TOKEN", default="")


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Muat .env lalu file konfigurasi.

    Urutan pemilihan file config:
      1. argumen `path` (mis. dari flag --config)
      2. environment variable ABSENIA_CONFIG
      3. default: config.yaml (produksi)
    Path relatif di-resolve terhadap root proyek.
    """
    load_dotenv(ROOT / ".env")
    chosen = path or os.getenv("ABSENIA_CONFIG")
    cfg_path = Path(chosen) if chosen else (ROOT / "config.yaml")
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    if not cfg_path.exists():
        raise FileNotFoundError(f"File config tidak ditemukan: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(raw=raw)
