"""Управление громкостью (порт Windows/Volume/VolumeService.cs).

C# использует P/Invoke/COM CoreAudio (IMMDeviceEnumerator, IAudioEndpointVolume);
по спецификации всё повторяется через pycaw (AudioUtilities → EndpointVolume).
Каждый публичный метод, как и в C#, оборачивает работу в try/catch → False.
"""

from __future__ import annotations

from pycaw.pycaw import AudioUtilities

# Шаг ±громкости: в C# VolumeUp/VolumeDown посылали один APPCOMMAND
# (системный шаг Windows, ≈2%); здесь — эквивалентный scalar-шаг pycaw.
VOLUME_STEP = 0.02


class VolumeService:
    @staticmethod
    def _endpoint_volume():
        # C#: MMDeviceEnumerator → GetDefaultAudioEndpoint(DataFlow.Render,
        # Role.Multimedia) → IAudioEndpointVolume
        device = AudioUtilities.GetSpeakers()
        return device.EndpointVolume

    def volume_up(self) -> bool:
        try:
            volume = self._endpoint_volume()
            current = volume.GetMasterVolumeLevelScalar()
            level = min(1.0, current + VOLUME_STEP)
            volume.SetMasterVolumeLevelScalar(level, None)
            return True
        except Exception:
            return False

    def volume_down(self) -> bool:
        try:
            volume = self._endpoint_volume()
            current = volume.GetMasterVolumeLevelScalar()
            level = max(0.0, current - VOLUME_STEP)
            volume.SetMasterVolumeLevelScalar(level, None)
            return True
        except Exception:
            return False

    def mute(self) -> bool:
        try:
            # C#: volume.SetMute(true, Guid.Empty)
            volume = self._endpoint_volume()
            volume.SetMute(1, None)
            return True
        except Exception:
            return False

    def un_mute(self) -> bool:
        try:
            # C#: volume.SetMute(false, Guid.Empty)
            volume = self._endpoint_volume()
            volume.SetMute(0, None)
            return True
        except Exception:
            return False

    # Алиас имени UnMute → snake_case для удобства вызова.
    unmute = un_mute

    def set_volume(self, value: int) -> bool:
        try:
            # Math.Clamp(value, 0, 100)
            value = max(0, min(100, value))

            # C#: volume.SetMasterVolumeLevelScalar(value / 100.0f, Guid.Empty)
            volume = self._endpoint_volume()
            volume.SetMasterVolumeLevelScalar(value / 100.0, None)
            return True
        except Exception:
            return False
