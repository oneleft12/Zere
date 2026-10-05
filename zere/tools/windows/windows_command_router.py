"""Парсер команд питания Windows (порт Windows/WindowsCommandRouter.cs)."""

from __future__ import annotations

from zere.tools.windows.windows_command_type import WindowsCommandType


class WindowsCommandRouter:
    # Ключевые слова-стемы команд питания (для поиска отрицания перед ними).
    _POWER_STEMS = (
        "выключ",
        "выруб",
        "перезагруз",
        "перезапусти",
        "заверши",
        "заморозь",
        "уходи спать",
        "shutdown",
        "restart",
        "reboot",
        "рестарт",
    )

    @classmethod
    def is_negated(cls, text: str) -> bool:
        """Есть ли в сообщении отрицание команды питания.

        «не выключай компьютер», «нет, перезагружай сам», «я бы не shutdown» —
        такие фразы не должны распознаваться как команды.
        """
        tokens = [t for t in text.replace(",", " ").split() if t]

        if not tokens:
            return False

        # Отрицание в начале фразы: «не выключай…», «нет, вырубай сам».
        if tokens[0] in ("не", "нет"):
            return True

        # Отрицание непосредственно перед ключевым словом:
        # «точно не выключай», «я бы не перезагружал».
        for prev, token in zip(tokens, tokens[1:]):
            if prev not in ("не", "нет"):
                continue
            if any(stem in token for stem in cls._POWER_STEMS):
                return True

        return False

    def parse(self, message: str) -> WindowsCommandType:
        text = message.lower().strip()

        # Отрицания — не команды («не выключай компьютер» → NONE,
        # ответ отдаётся LLM).
        if self.is_negated(text):
            return WindowsCommandType.NONE

        # Команды звука не относятся к Windows Power.
        if (
            "звук" in text
            or "громкость" in text
            or "громче" in text
            or "тише" in text
            or "mute" in text
            or "unmute" in text
        ):
            return WindowsCommandType.NONE

        # === Выключение ===
        if (
            "выключи компьютер" in text
            or "выключить компьютер" in text
            or "выруби компьютер" in text
            or "выключай компьютер" in text
            or "выключи комп" in text
            or "выключить комп" in text
            or "выруби комп" in text
            or "выключай комп" in text
            or "заверши работу" in text
            or "shutdown" in text
            or "power off" in text
            or "выключи пк" in text
            or "выключить пк" in text
            or "выруби пк" in text
        ):
            return WindowsCommandType.SHUTDOWN

        # === Перезагрузка ===
        if (
            "перезагрузи компьютер" in text
            or "перезагрузить компьютер" in text
            or "перезагрузи комп" in text
            or "перезагрузить комп" in text
            # Существительное — только как самостоятельная команда,
            # иначе «после перезагрузки файлы сохранятся?» запрашивало рестарт.
            or text == "перезагрузка"
            or text.startswith("перезагрузка ")
            or "reboot" in text
            or "restart" in text
            or "рестарт" in text
            or "перезагрузи пк" in text
            or "перезагрузить пк" in text
            or "перезапусти компьютер" in text
            or "перезапусти комп" in text
        ):
            return WindowsCommandType.RESTART

        # === Сон ===
        if (
            text == "сон"
            or "режим сна" in text
            or "спящий режим" in text
            or "компьютер в сон" in text
            or "комп в сон" in text
            or "заморозь" in text
            or "hibernate" in text
            or "hybernate" in text
            or "уходи спать" in text
        ):
            return WindowsCommandType.SLEEP

        return WindowsCommandType.NONE
