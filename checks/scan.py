"""QR image decoding for the camera scanner.

Takes encoded image bytes (JPEG/PNG from the camera) and returns the QR text.
Uses OpenCV, which Flet hosts prebuilt for Android and iOS, so the same code
runs on desktop, in the browser build's server, and on the phone.

cv2/numpy are imported lazily so the rest of the app still starts if they
are not installed; the scan button just reports that it is unavailable.
"""
from __future__ import annotations


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def decode_qr(image_bytes: bytes) -> str | None:
    """Return the first QR code's text found in the image, or None."""
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    attempts = [(img, "aruco"), (gray, "classic")]
    # Small or distant codes decode more often after upscaling.
    if max(gray.shape) < 1200:
        up = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        attempts.append((up, "aruco"))

    aruco = cv2.QRCodeDetectorAruco()
    classic = cv2.QRCodeDetector()
    for frame, kind in attempts:
        det = aruco if kind == "aruco" else classic
        try:
            text, _points, _straight = det.detectAndDecode(frame)
        except cv2.error:
            continue
        if text:
            return text
    return None
