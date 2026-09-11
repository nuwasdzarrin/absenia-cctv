"""Sumber frame kamera: RTSP (produksi/CCTV) atau Webcam (uji coba).

Keduanya berbagi antarmuka sama:
    with make_camera(cfg) as cam:
        frame = cam.read()   # frame BGR numpy, atau None bila gagal

`make_camera(cfg)` memilih sumber berdasarkan `camera.source` di config.yaml:
    source: webcam  -> WebcamCamera (cv2.VideoCapture(index))   ← untuk testing
    source: rtsp    -> RtspCamera   (stream Tapo)               ← untuk produksi
"""
from __future__ import annotations

import logging
import time
from types import TracebackType

import cv2
import numpy as np

log = logging.getLogger("absenia.camera")


class BaseCamera:
    """Kerangka umum: buka koneksi, baca frame terbaru, reconnect otomatis."""

    label = "camera"

    def __init__(self, reconnect_delay_sec: int = 5) -> None:
        self.reconnect_delay_sec = reconnect_delay_sec
        self.cap: cv2.VideoCapture | None = None

    # subclass mengisi cara membuat VideoCapture
    def _make_capture(self) -> cv2.VideoCapture:  # pragma: no cover - override
        raise NotImplementedError

    def open(self) -> bool:
        self.cap = self._make_capture()
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        ok = self.cap.isOpened()
        if ok:
            log.info("Terhubung ke %s.", self.label)
        else:
            log.warning("Gagal membuka %s.", self.label)
        return ok

    def read(self, retries: int = 3) -> np.ndarray | None:
        for attempt in range(1, retries + 1):
            if self.cap is None or not self.cap.isOpened():
                if not self.open():
                    time.sleep(self.reconnect_delay_sec)
                    continue
            assert self.cap is not None
            # buang beberapa frame agar dapat yang paling baru (hindari lag buffer)
            for _ in range(2):
                self.cap.grab()
            ok, frame = self.cap.read()
            if ok and frame is not None:
                return frame
            log.warning("Gagal membaca frame dari %s (percobaan %d/%d), reconnect...",
                        self.label, attempt, retries)
            self.release()
            time.sleep(self.reconnect_delay_sec)
        return None

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self) -> "BaseCamera":
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class RtspCamera(BaseCamera):
    def __init__(self, url: str, url_masked: str, reconnect_delay_sec: int = 5) -> None:
        super().__init__(reconnect_delay_sec)
        self.url = url
        self.label = f"kamera RTSP {url_masked}"

    def _make_capture(self) -> cv2.VideoCapture:
        # FFMPEG backend lebih stabil untuk RTSP Tapo.
        return cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)


class WebcamCamera(BaseCamera):
    def __init__(self, index: int = 0, reconnect_delay_sec: int = 2) -> None:
        super().__init__(reconnect_delay_sec)
        self.index = index
        self.label = f"webcam #{index}"

    def _make_capture(self) -> cv2.VideoCapture:
        # CAP_DSHOW mempercepat pembukaan webcam di Windows.
        return cv2.VideoCapture(self.index, cv2.CAP_DSHOW)


def make_camera(cfg) -> BaseCamera:
    """Factory: pilih sumber kamera dari config.yaml (camera.source)."""
    cam_cfg = cfg.camera
    source = str(cam_cfg.get("source", "rtsp")).lower()
    delay = int(cam_cfg.get("reconnect_delay_sec", 5))
    if source == "webcam":
        return WebcamCamera(int(cam_cfg.get("webcam_index", 0)), reconnect_delay_sec=2)
    return RtspCamera(cfg.rtsp_url(), cfg.rtsp_url(masked=True), reconnect_delay_sec=delay)
