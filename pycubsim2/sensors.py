from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SensorFrame:
    rgb: np.ndarray
    depth_m: np.ndarray
    depth_rgb: np.ndarray
    segmentation: np.ndarray
    segmentation_rgb: np.ndarray
    source: str


def depth_colormap(
    depth_m: np.ndarray,
    near: float = 0.02,
    far: float = 10.0,
) -> np.ndarray:
    valid = np.isfinite(depth_m) & (depth_m > near) & (depth_m < far * 0.995)
    low = max(near, 0.05)
    high = min(far * 0.995, 5.0)
    log_depth = np.log(np.clip(depth_m, low, high))
    value = 1.0 - np.clip(
        (log_depth - math.log(low)) / max(1e-6, math.log(high) - math.log(low)),
        0.0,
        1.0,
    )
    stops = np.asarray(
        (
            (0.04, 0.07, 0.20),
            (0.02, 0.54, 0.70),
            (0.44, 0.78, 0.36),
            (0.96, 0.72, 0.16),
            (0.88, 0.12, 0.10),
        ),
        dtype=np.float32,
    )
    scaled = value * (len(stops) - 1)
    lower_index = np.floor(scaled).astype(np.int32)
    upper_index = np.clip(lower_index + 1, 0, len(stops) - 1)
    fraction = (scaled - lower_index)[..., None]
    rgb = stops[lower_index] * (1.0 - fraction) + stops[upper_index] * fraction
    rgb[~valid] = 0.0
    return np.asarray(np.clip(rgb * 255.0, 0, 255), dtype=np.uint8)


def segmentation_colormap(segmentation: np.ndarray) -> np.ndarray:
    values = np.asarray(segmentation, dtype=np.int64)
    body_ids = values & ((1 << 24) - 1)
    link_ids = (values >> 24) - 1
    red = (body_ids * 67 + link_ids * 29 + 53) % 256
    green = (body_ids * 131 + link_ids * 47 + 97) % 256
    blue = (body_ids * 193 + link_ids * 71 + 151) % 256
    rgb = np.stack((red, green, blue), axis=-1).astype(np.uint8)
    rgb[values < 0] = 0
    return rgb


class WebcamCapture:
    def __init__(self) -> None:
        self._capture = None
        self.index = -1
        self.error = ""

    def retry(self) -> None:
        self.error = ""

    def open(self, index: int, width: int, height: int) -> None:
        if self._capture is not None and self.index == index:
            return
        if self.error:
            raise RuntimeError(self.error)
        self.close()
        try:
            import cv2
        except ImportError as exc:
            self.error = "OpenCV is required for webcam input."
            raise RuntimeError(self.error) from exc
        try:
            capture = cv2.VideoCapture(index)
        except Exception as exc:
            self.error = f"Could not initialize webcam {index}: {exc}"
            raise RuntimeError(self.error) from exc
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not capture.isOpened():
            capture.release()
            self.error = (
                f"Could not open webcam {index}. Check macOS camera permission."
            )
            raise RuntimeError(self.error)
        self._capture = capture
        self.index = int(index)
        self.error = ""

    def read(self, index: int, width: int, height: int) -> np.ndarray:
        self.open(index, width, height)
        assert self._capture is not None
        ok, frame = self._capture.read()
        if not ok:
            self.error = f"Webcam {index} did not return a frame."
            self.close()
            raise RuntimeError(self.error)
        import cv2

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if frame.shape[1] != width or frame.shape[0] != height:
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        return np.asarray(frame, dtype=np.uint8)

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
        self.index = -1
