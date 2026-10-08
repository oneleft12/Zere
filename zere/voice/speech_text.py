"""Чистка текста для TTS и разбивка на предложения (порт SpeechText.cs).

Общий модуль для всех TTS-движков (ChatTTS, Silero): раньше функции жили
внутри `chattts_manager`, но они не про ChatTTS, а про текст. C#-редакция
держит их в `ZERE.Voice/Text/SpeechText.cs` — здесь паритет.

Почему разбивка на предложения вообще нужна: нейросетевые движки заметно
ровнее звучат на коротких фрагментах, а вызывающий код получает первый звук
раньше (синтез идёт по предложению за раз).
"""

from __future__ import annotations

import re

__all__ = ["split_sentences", "strip_emotions"]

_RE_SENTENCE = re.compile(r'[^.!?…]+[.!?…]+[»""\']*\s*|[^.!?…]+$')


def strip_emotions(text: str) -> str:
    """Убирает из текста всё, что TTS не должен произносить.

    Порт PiperService.strip_emotions / SpeechText.Clean: эмодзи, текстовые
    смайлики, «ролевые» пометки (*улыбается*, (томно)), markdown-разметка.
    """
    if not text:
        return text

    # Ролевые пометки в скобках: (улыбается), (смеётся), (задумчиво)
    text = re.sub(r"\([^)]*[а-яёА-ЯЁ]{3,}[^)]*\)", " ", text)

    # Ролевые пометки в *звёздочках*: *улыбается*, *качает головой*
    text = re.sub(r"\*[^*]*[а-яёА-ЯЁ]{3,}[^*]*\*", " ", text)

    # Markdown-эмодзи :smile:, :heart:
    text = re.sub(r":[a-z_0-9]+:", " ", text)

    # Текстовые смайлики: :) ;) :D :( :P <3 =) и т.п.
    text = re.sub(r"[:;=8][\-^']?[)(DPp/\\|]", " ", text)
    text = re.sub(r"[)(DPp/\\|][\-^']?[:;=8]", " ", text)
    text = re.sub(r"<3", " ", text)

    # Юникод-эмодзи и символы (астральные + BMP-диапазоны символов)
    text = re.sub(
        r"[\U00010000-\U0010FFFF]|[️‍]"
        r"|[☀-➿]|[←-⇿]|[⬀-⯿]|[✀-➿]",
        "",
        text,
    )

    # Убираем markdown-разметку: **bold**, *italic*, `code`, ## заголовки
    text = re.sub(r"[*_`#]{1,3}([^*_`#]+)[*_`#]{1,3}", r"\1", text)
    text = re.sub(r"[*_`#~>|-]{2,}", " ", text)

    # Схлопываем пробелы
    return re.sub(r"\s{2,}", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    """Разбивает текст на предложения (порт SpeechText.SplitSentences)."""
    parts = [m.group(0).strip() for m in _RE_SENTENCE.finditer(text or "")]
    parts = [p for p in parts if p]

    if parts:
        return parts

    stripped = (text or "").strip()
    return [stripped] if stripped else []
