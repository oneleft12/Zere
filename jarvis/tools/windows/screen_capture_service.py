"""Захват экрана (порт Windows/ScreenCaptureService.cs; System.Drawing → mss + Pillow)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mss import mss
from PIL import Image


class ScreenCaptureService:
    def capture(self) -> str:
        # Environment.SpecialFolder.Desktop
        desktop = Path.home() / "Desktop"

        folder = desktop / "JARVIS Screenshots"
        folder.mkdir(parents=True, exist_ok=True)

        file = folder / f"Screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"

        with mss() as sct:
            # PrimaryScreen.Bounds → monitors[1] (monitors[0] — все экраны)
            monitor = sct.monitors[1]

            shot = sct.grab(monitor)

            image = Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
            image.save(str(file))

        return str(file)
