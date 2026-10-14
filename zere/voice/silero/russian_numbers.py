"""Числа прописью по-русски — без зависимостей (для Silero v5_5_ru).

Зачем свой модуль, а не num2words: у `v5_5_ru` в наборе символов НЕТ цифр
(`model.symbols = "_~|!+,-.:;?абвгдежзийклмнопрстуфхцчшщъыьэюяё–… "`), поэтому
`apply_tts` молча выбрасывает их — замер микрофоном через faster-whisper:
«В 2026 году» модель произносит как «В году», «Цена 1500 рублей» — как «Цена
рублей», а «2026» целиком падает с `ValueError` (после чистки не остаётся ни
одного символа). Значит цифры нужно раскрывать в слова ДО синтеза.

num2words — лишняя зависимость сразу в двух местах (в окружении ZERE и в
сайдкаре C#-редакции, `uv run --with num2words`), а задача закрывается
небольшим собственным модулем: кардиналы до 10^15, порядковые (нужны для годов
и дат — «две тысячи двадцать шестой год»), согласование с существительными
(«один процент», «два процента», «пять процентов»).

Грамматика — не «машинный» перевод числа, а нормативный русский:
`integer_to_words(1500) == "тысяча пятьсот"`,
`ordinal_to_words(2026, "m", "pre") == "две тысячи двадцать шестом"`.
"""

from __future__ import annotations

__all__ = [
    "agree",
    "decimal_to_words",
    "integer_to_words",
    "ordinal_to_words",
]

# ── Кардиналы ───────────────────────────────────────────────────────

#: Единицы: мужской род («один час») и женский («одна минута», «две тысячи»).
_UNITS_MASCULINE = (
    "ноль", "один", "два", "три", "четыре",
    "пять", "шесть", "семь", "восемь", "девять",
)
_UNITS_FEMININE = (
    "ноль", "одна", "две", "три", "четыре",
    "пять", "шесть", "семь", "восемь", "девять",
)

#: 10..19 — отдельный ряд: «одиннадцать», а не «один на десять».
_TEENS = (
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
    "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
)

_TENS = (
    "", "", "двадцать", "тридцать", "сорок",
    "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто",
)

_HUNDREDS = (
    "", "сто", "двести", "триста", "четыреста",
    "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот",
)

#: Разряды по три цифры: (ед. ч., 2..4, много, женский род).
_GROUPS: tuple[tuple[str, str, str, bool], ...] = (
    ("", "", "", False),
    ("тысяча", "тысячи", "тысяч", True),
    ("миллион", "миллиона", "миллионов", False),
    ("миллиард", "миллиарда", "миллиардов", False),
    ("триллион", "триллиона", "триллионов", False),
)

#: Разряды «составных» порядковых: 2000 → «двухтысячный».
_GROUP_ORDINALS = ("", "тысячный", "миллионный", "миллиардный", "триллионный")


def agree(count: int, forms: tuple[str, str, str]) -> str:
    """Выбирает форму существительного по числу: (1, 2..4, 5+).

    `agree(1, ("процент", "процента", "процентов")) == "процент"`,
    `agree(22, ...) == "процента"`, `agree(11, ...) == "процентов"`.
    """
    tail = abs(int(count)) % 100

    if 11 <= tail <= 14:
        return forms[2]

    tail %= 10

    if tail == 1:
        return forms[0]
    if 2 <= tail <= 4:
        return forms[1]

    return forms[2]


def _triple_to_words(value: int, feminine: bool = False) -> str:
    """0..999 прописью (с учётом рода для «одна тысяча» / «две минуты»)."""
    units = _UNITS_FEMININE if feminine else _UNITS_MASCULINE
    parts: list[str] = []

    hundreds, rest = divmod(value, 100)
    if hundreds:
        parts.append(_HUNDREDS[hundreds])

    if 10 <= rest <= 19:
        parts.append(_TEENS[rest - 10])
        return " ".join(parts)

    tens, unit = divmod(rest, 10)
    if tens:
        parts.append(_TENS[tens])
    if unit:
        parts.append(units[unit])

    return " ".join(parts)


def integer_to_words(value: int, feminine: bool = False) -> str:
    """Целое число прописью: 1500 → «тысяча пятьсот», -7 → «минус семь»."""
    number = int(value)

    if number == 0:
        return "ноль"

    sign = "минус " if number < 0 else ""

    digits = str(abs(number))
    triples: list[int] = []
    while digits:
        triples.append(int(digits[-3:]))
        digits = digits[:-3]

    parts: list[str] = []
    first_group = True

    for index in range(len(triples) - 1, -1, -1):
        triple = triples[index]

        # Нулевые разряды пропускаем: 1000 → «тысяча», а не «одна тысяча
        # ноль» (сам ноль обработан выше).
        if triple == 0:
            continue

        group = _GROUPS[index]

        if index == 0:
            # Род задаёт только младший разряд: «одна минута», но «тысяча один».
            parts.append(_triple_to_words(triple, feminine))
        elif triple == 1 and first_group:
            # «тысяча пятьсот», а не «одна тысяча пятьсот»: в живой речи
            # ведущая единица у круглых разрядов опускается.
            parts.append(group[0])
        else:
            parts.append(_triple_to_words(triple, group[3]))
            parts.append(agree(triple, (group[0], group[1], group[2])))

        first_group = False

    return sign + " ".join(parts)


# ── Порядковые (годы, даты, «5-й») ──────────────────────────────────

_ORDINAL_UNITS = (
    "", "первый", "второй", "третий", "четвёртый",
    "пятый", "шестой", "седьмой", "восьмой", "девятый",
)

_ORDINAL_TEENS = (
    "десятый", "одиннадцатый", "двенадцатый", "тринадцатый", "четырнадцатый",
    "пятнадцатый", "шестнадцатый", "семнадцатый", "восемнадцатый", "девятнадцатый",
)

_ORDINAL_TENS = (
    "", "", "двадцатый", "тридцатый", "сороковой",
    "пятидесятый", "шестидесятый", "семидесятый", "восьмидесятый", "девяностый",
)

_ORDINAL_HUNDREDS = (
    "", "сотый", "двухсотый", "трёхсотый", "четырёхсотый",
    "пятисотый", "шестисотый", "семисотый", "восьмисотый", "девятисотый",
)

#: Формы для «составных» разрядов: 2 тысячи → «двухтысячный».
_COMBINING_UNITS = (
    "", "одно", "двух", "трёх", "четырёх",
    "пяти", "шести", "семи", "восьми", "девяти",
)

_COMBINING_TENS = (
    "", "", "двадцати", "тридцати", "сорока",
    "пятидесяти", "шестидесяти", "семидесяти", "восьмидесяти", "девяноста",
)

_COMBINING_HUNDREDS = (
    "", "сто", "двухсот", "трёхсот", "четырёхсот",
    "пятисот", "шестисот", "семисот", "восьмисот", "девятисот",
)

#: Окончания порядковых по (род, падеж): (твёрдое, на «-ой», мягкое).
#: «третий» — мягкого склонения, «второй/шестой» — с ударным окончанием.
_ORDINAL_ENDINGS = {
    ("m", "nom"): ("ый", "ой", "ий"),
    ("m", "gen"): ("ого", "ого", "ьего"),
    ("m", "dat"): ("ому", "ому", "ьему"),
    ("m", "ins"): ("ым", "ым", "ьим"),
    ("m", "pre"): ("ом", "ом", "ьем"),
    ("f", "nom"): ("ая", "ая", "ья"),
    ("f", "gen"): ("ой", "ой", "ьей"),
    ("f", "dat"): ("ой", "ой", "ьей"),
    ("f", "ins"): ("ой", "ой", "ьей"),
    ("f", "pre"): ("ой", "ой", "ьей"),
    ("n", "nom"): ("ое", "ое", "ье"),
    ("n", "gen"): ("ого", "ого", "ьего"),
    ("n", "dat"): ("ому", "ому", "ьему"),
    ("n", "ins"): ("ым", "ым", "ьим"),
    ("n", "pre"): ("ом", "ом", "ьем"),
    ("pl", "nom"): ("ые", "ые", "ьи"),
    ("pl", "gen"): ("ых", "ых", "ьих"),
    ("pl", "dat"): ("ым", "ым", "ьим"),
    ("pl", "ins"): ("ыми", "ыми", "ьими"),
    ("pl", "pre"): ("ых", "ых", "ьих"),
}


def _combining(value: int) -> str:
    """«Слитная» форма множителя: 25 → «двадцатипяти» (для «двадцатипятитысячный»)."""
    hundreds, rest = divmod(value, 100)
    parts: list[str] = []

    if hundreds:
        parts.append(_COMBINING_HUNDREDS[hundreds])

    if 10 <= rest <= 19:
        # «одиннадцати», «двенадцати» — берём косвенную основу из порядковых
        parts.append(_ORDINAL_TEENS[rest - 10][:-2] + "и")
        return "".join(parts)

    tens, unit = divmod(rest, 10)
    if tens:
        parts.append(_COMBINING_TENS[tens])
    if unit:
        parts.append(_COMBINING_UNITS[unit])

    return "".join(parts)


def _ordinal_under_1000(value: int) -> str:
    """Порядковое для 1..999: 125 → «сто двадцать пятый»."""
    parts: list[str] = []
    number = value

    hundreds, number = divmod(number, 100)
    if hundreds:
        parts.append(_HUNDREDS[hundreds] if number else _ORDINAL_HUNDREDS[hundreds])
        if not number:
            return " ".join(parts)

    if 10 <= number <= 19:
        parts.append(_ORDINAL_TEENS[number - 10])
        return " ".join(parts)

    tens, unit = divmod(number, 10)
    if tens:
        parts.append(_ORDINAL_TENS[tens] if not unit else _TENS[tens])
    if unit:
        parts.append(_ORDINAL_UNITS[unit])

    return " ".join(parts)


def _decline(ordinal: str, gender: str, case: str) -> str:
    """Склоняет порядковое слово: «первый» + (f, gen) → «первой».

    Меняются только последние два символа, поэтому функция работает и с
    составным числительным: «сто двадцать пятый» + (m, gen) → «сто двадцать
    пятого» — склоняется последнее слово, как и положено.
    """
    endings = (
        _ORDINAL_ENDINGS.get((gender, case))
        or _ORDINAL_ENDINGS.get(("m", case))
        or _ORDINAL_ENDINGS[("m", "nom")]
    )

    tail = ordinal[-2:]

    if tail == "ой":
        index = 1
    elif tail == "ий":
        index = 2
    else:
        index = 0

    return ordinal[:-2] + endings[index]


def ordinal_to_words(value: int, gender: str = "m", case: str = "nom") -> str:
    """Порядковое числительное: 2026 (m, pre) → «две тысячи двадцать шестом».

    В составном числительном склоняется только последнее слово
    («две тысячи двадцать шестой»), но у круглых тысяч порядковое слитное:
    2000 → «двухтысячный», 50000 → «пятидесятитысячный».
    """
    number = abs(int(value))

    if number == 0:
        return _decline("нулевой", gender, case)

    # Круглые разряды (2000, 100000, 2000000) — слитная форма («двухтысячный»).
    if number >= 1000:
        for index in range(len(_GROUPS) - 1, 0, -1):
            scale = 1000 ** index
            if number % scale == 0 and number >= scale:
                multiplier = number // scale
                prefix = "" if multiplier == 1 else _combining(multiplier)
                return _decline(prefix + _GROUP_ORDINALS[index], gender, case)

    if number < 1000:
        return _decline(_ordinal_under_1000(number), gender, case)

    # Хвост (младшие три цифры) — порядковое, старшие — обычные слова.
    tail = number % 1000
    head = number - tail

    if tail == 0:
        return _decline(_ordinal_under_1000(number), gender, case)

    return f"{integer_to_words(head)} {_decline(_ordinal_under_1000(tail), gender, case)}"


# ── Дроби ───────────────────────────────────────────────────────────

_FRACTION_FORMS = {
    1: ("десятая", "десятых", "десятых"),
    2: ("сотая", "сотых", "сотых"),
    3: ("тысячная", "тысячных", "тысячных"),
}


def decimal_to_words(raw: str) -> str:
    """Дробь прописью: «3.5» → «три целых пять десятых».

    Разделитель — точка или запятая (в русском тексте чаще запятая). Дольше
    трёх знаков после запятой — читаем по цифрам («3.14159» → «три точка один
    четыре один пять девять»): «стотысячных» в живой речи не бывает.
    """
    text = str(raw).strip().replace(",", ".")
    whole, _, fraction = text.partition(".")

    whole_value = int(whole or 0)
    whole_words = integer_to_words(whole_value, feminine=True)

    fraction = fraction.rstrip("0")

    if not fraction:
        return whole_words

    if len(fraction) > 3:
        digits = " ".join(_UNITS_MASCULINE[int(char)] for char in fraction)
        return f"{whole_words} точка {digits}"

    fraction_value = int(fraction)
    forms = _FRACTION_FORMS[len(fraction)]

    return (
        f"{whole_words} {agree(whole_value, ('целая', 'целых', 'целых'))} "
        f"{integer_to_words(fraction_value, feminine=True)} {agree(fraction_value, forms)}"
    )
