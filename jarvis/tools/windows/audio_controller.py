"""Аудио-контроллер: медиаклавиши громкости (порт Windows/AudioController.cs)."""

from __future__ import annotations

import ctypes

KEYEVENTF_KEYUP = 0x0002

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF


class AudioController:
    def _press(self, key: int) -> None:
        # [DllImport("user32.dll")] keybd_event(byte bVk, byte bScan, int dwFlags, int dwExtraInfo)
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        ctypes.windll.user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)

    def volume_up(self) -> None:
        for _ in range(5):
            self._press(VK_VOLUME_UP)

    def volume_down(self) -> None:
        for _ in range(5):
            self._press(VK_VOLUME_DOWN)

    def toggle_mute(self) -> None:
        self._press(VK_VOLUME_MUTE)
