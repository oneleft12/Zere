"""Порт JARVIS.Core/Handlers/VolumeHandler.cs."""

from __future__ import annotations

from jarvis.core.handlers.i_jarvis_handler import IJarvisHandler
from jarvis.tools.windows.volume.volume_command_router import VolumeCommandRouter
from jarvis.tools.windows.volume.volume_command_type import VolumeCommandType
from jarvis.tools.windows.volume.volume_service import VolumeService


class VolumeHandler(IJarvisHandler):
    def __init__(self, service: VolumeService) -> None:
        self._service = service
        self._router = VolumeCommandRouter()

    def can_handle(self, message: str) -> bool:
        lower = message.lower()

        return (
            lower.startswith("громкость")
            or "сделай громче" in lower
            or "сделай тише" in lower
            or "выключи звук" in lower
            or "включи звук" in lower
            or "громче" in lower
            or "тише" in lower
            or "прибавь" in lower
            or "убавь" in lower
            or "увеличь громкость" in lower
            or "уменьши громкость" in lower
            or "погромче" in lower
            or "потише" in lower
            or "замути" in lower
            or "размути" in lower
            or "приглуши" in lower
            or "mute" in lower
            or "unmute" in lower
            or "без звука" in lower
            or "верни звук" in lower
            or "звук вверх" in lower
            or "звук вниз" in lower
            or "громкость вверх" in lower
            or "громкость вниз" in lower
            or "больше звука" in lower
            or "меньше звука" in lower
        )

    def handle(self, message: str) -> str:
        command = self._router.parse(message)

        if command.type == VolumeCommandType.SetVolume:
            return (
                f"Громкость установлена на {command.value}%."
                if self._service.set_volume(command.value)
                else "Не удалось изменить громкость."
            )

        if command.type == VolumeCommandType.VolumeUp:
            return "Громкость увеличена." if self._service.volume_up() else "Не удалось увеличить громкость."

        if command.type == VolumeCommandType.VolumeDown:
            return "Громкость уменьшена." if self._service.volume_down() else "Не удалось уменьшить громкость."

        if command.type == VolumeCommandType.Mute:
            return "Звук выключен." if self._service.mute() else "Не удалось выключить звук."

        if command.type == VolumeCommandType.UnMute:
            return "Звук включён." if self._service.un_mute() else "Не удалось включить звук."

        return "Команда громкости не распознана."
