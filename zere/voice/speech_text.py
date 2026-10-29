"""Чистка текста для TTS и разбивка на предложения (порт SpeechText.cs).

Общий модуль TTS (Silero): раньше функции жили внутри менеджера движка,
но они не про движок, а про текст. C#-редакция
держит их в `ZERE.Voice/Text/SpeechText.cs` — здесь паритет.

Почему разбивка на предложения вообще нужна: нейросетевые движки заметно
ровнее звучат на коротких фрагментах, а вызывающий код получает первый звук
раньше (синтез идёт по предложению за раз).
"""

from __future__ import annotations

import re

__all__ = ["split_sentences", "strip_emotions"]

#: Конец предложения: «.», «!», «?», «…» — но НЕ точка между цифрами.
#: Раньше «Цена 3.5 рублей.» резалась на «Цена 3.» и «5 рублей.»: точка в
#: числе считалась концом фразы, и синтез читал «цена три» + «пять рублей»
#: (для Silero это ещё и попадало в раскрытие чисел посреди числа).
_RE_SENTENCE_END = re.compile(r"[.!?…]+(?!\d)")

#: Закрывающие кавычки/скобки сразу после знака — часть предложения.
_CLOSERS = "»”\"')]"


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
    """Разбивает текст на предложения (порт SpeechText.SplitSentences).

    Точка внутри числа предложением не считается: «3.5», «12.05.2026» и
    «1.2.3» остаются целыми (иначе число рвётся на две реплики и читается
    как «три» + «пять»).
    """
    source = (text or "").strip()

    if not source:
        return []

    parts: list[str] = []
    start = 0

    for match in _RE_SENTENCE_END.finditer(source):
        end = match.end()

        while end < len(source) and source[end] in _CLOSERS:
            end += 1

        chunk = source[start:end].strip()

        if chunk:
            parts.append(chunk)

        start = end

    tail = source[start:].strip()

    if tail:
        parts.append(tail)

    return parts
