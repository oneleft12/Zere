"""Нормализация текста для РУССКОЙ модели Silero v5_5_ru.

Проблема, из-за которой модуль существует (замер по синтезу самой модели,
расшифровка faster-whisper):

    model.symbols = "_~|!+,-.:;?абвгдежзийклмнопрстуфхцчшщъыьэюяё–… "

В наборе символов модели НЕТ ни цифр, ни латиницы, а `apply_tts` МОЛЧА
выбрасывает всё, чего не знает:

    «В 2026 году»         → слышно «В году»
    «Цена 1500 рублей»    → «Цена рублей»
    «Открой GitHub»       → «Открой» (латиница выпадает)
    «GitHub» целиком      → ValueError: пустой текст после чистки

Поэтому текст раскрывается в кириллицу ДО синтеза:

* цифры → слова по-русски (`russian_numbers`): числа, дроби, проценты, годы
  («в 2026 году» → «в две тысячи двадцать шестом году»), даты, время, единицы;
* латиница → практическая транскрипция («GitHub» → «Гитхаб») плюс словарь
  частых терминов; сокращения из заглавных читаются по буквам («CS2» → «си эс
  два»);
* символы, которых нет в наборе (`%`, `№`, `&`, `@`, `=`, `×`, валюты), → слова,
  а вовсе нечитаемое (эмодзи, кавычки, длинное тире `—`) вырезается или
  заменяется паузой — иначе символ исчезает из речи и может склеить слова.

Почему транскрипция, а не английская модель Silero: вторая модель — это ещё
~150 МБ и переключение графа на каждой фразе, а английские вставки в русской
речи короткие («открой GitHub», «iPhone 15»). Словарь закрывает частые
термины, правила — остальное.

Модуль чистый (без torch/numpy) и total: на любом входе возвращает строку,
ничего не бросает. Гарантия контракта: после `normalize()` в тексте не остаётся
ничего, чего модель не умеет читать, — ни латиницы, ни цифр, ни эмодзи.
"""

from __future__ import annotations

import re

from zere.voice.silero.russian_numbers import (
    agree,
    decimal_to_words,
    integer_to_words,
    ordinal_to_words,
)

__all__ = ["expand_numbers", "normalize", "transliterate_latin"]

# ── Словарь частых слов и терминов ──────────────────────────────────
#
# Ключ — латиница в нижнем регистре, значение — как это произносит русский
# человек. Словарь проверяется ДО правил: правила читают «GitHub» как
# «Джитхуб» (g перед i → «дж»), а «Google» с правилами и так выходит «Гугл».

_WORDS = {
    # Своё
    "zere": "Зере",
    # Бренды и сервисы
    "github": "Гитхаб", "gitlab": "Гитлаб", "git": "гит",
    "google": "Гугл", "youtube": "Ютуб", "chrome": "Хром", "firefox": "Файрфокс",
    "telegram": "Телеграм", "discord": "Дискорд", "whatsapp": "Ватсап",
    "instagram": "Инстаграм", "facebook": "Фейсбук", "tiktok": "Тикток",
    "twitter": "Твиттер", "reddit": "Реддит", "wikipedia": "Википедия",
    "windows": "Виндовс", "linux": "Линукс", "ubuntu": "Убунту", "debian": "Дебиан",
    "fedora": "Федора", "android": "Андроид", "ios": "ай-ос", "macos": "мак-ос",
    "macbook": "Макбук", "iphone": "Айфон", "ipad": "Айпад", "airpods": "Эйрподс",
    "steam": "Стим", "minecraft": "Майнкрафт", "valorant": "Валорант",
    "roblox": "Роблокс", "nvidia": "Энвидиа", "intel": "Интел", "ryzen": "Райзен",
    "geforce": "Джифорс", "radeon": "Радион", "blender": "Блендер",
    "photoshop": "Фотошоп", "excel": "Эксель", "word": "Ворд", "outlook": "Аутлук",
    "powerpoint": "Пауэрпоинт", "figma": "Фигма", "notion": "Ноушен",
    "trello": "Трелло", "jira": "Джира", "zoom": "Зум", "slack": "Слак",
    "obs": "о-би-эс",
    # Технологии
    "python": "Питон", "javascript": "Джаваскрипт", "typescript": "Тайпскрипт",
    "java": "джава", "kotlin": "Котлин", "rust": "раст", "golang": "го",
    "docker": "Докер", "kubernetes": "Кубернетес", "ollama": "Оллама",
    "chatgpt": "Чат-Джи-Пи-Ти", "openai": "Опен-Эй-Ай", "deepseek": "Дипсик",
    "gemini": "Джемини", "claude": "Клод", "llama": "Лама", "mistral": "Мистраль",
    "api": "апи", "url": "ур-эл", "json": "джейсон", "html": "эйч-ти-эм-эл",
    "css": "си-эс-эс", "sql": "эс-кью-эл", "xml": "экс-эм-эл", "pdf": "пи-ди-эф",
    "png": "пи-эн-джи", "jpeg": "джейпег", "jpg": "джейпег", "gif": "гиф",
    "mp3": "эм-пи-три", "mp4": "эм-пи-четыре", "ai": "эй-ай", "ml": "эм-эл",
    "ui": "ю-ай", "ux": "ю-экс", "os": "о-эс", "pc": "пи-си", "usb": "ю-эс-би",
    "hdmi": "эйч-ди-эм-ай", "cpu": "си-пи-ю", "gpu": "джи-пи-ю", "ram": "рам",
    "ssd": "эс-эс-ди", "hdd": "эйч-ди-ди", "bios": "биос", "dns": "ди-эн-эс",
    "vpn": "ви-пи-эн", "ssh": "эс-эс-эйч", "ftp": "эф-ти-пи",
    "http": "эйч-ти-ти-пи", "https": "эйч-ти-ти-пи-эс", "ip": "ай-пи",
    "id": "ай-ди", "nasa": "Наса", "wi-fi": "вай-фай", "wifi": "вайфай",
    "bluetooth": "блютус", "gmail": "джимейл",
    # Частые английские слова (ассистент иногда отвечает вставками)
    "user": "юзер", "username": "юзернейм", "npm": "эн пи эм", "pip": "пип",
    "the": "зэ", "and": "энд", "of": "оф", "to": "ту", "for": "фо", "with": "виз",
    "you": "ю", "your": "ёр", "my": "май", "me": "ми", "is": "из", "are": "ар",
    "was": "воз", "not": "нот", "can": "кэн", "will": "вил", "let": "лет",
    "hello": "хеллоу", "hi": "хай", "ok": "окей", "okay": "окей", "yes": "ес",
    "no": "ноу", "thanks": "сэнкс", "thank": "сэнк", "please": "плиз",
    "sorry": "сорри", "bye": "бай", "help": "хелп", "test": "тест",
    "file": "файл", "folder": "фолдер", "cache": "кэш", "image": "имидж",
    "video": "видео", "audio": "аудио", "music": "мьюзик", "game": "гейм",
    "online": "онлайн", "offline": "оффлайн", "email": "имейл", "e-mail": "имейл",
    "site": "сайт", "web": "веб", "server": "сервер", "client": "клиент",
    "browser": "браузер", "driver": "драйвер", "update": "апдейт",
    "upgrade": "апгрейд", "download": "даунлоуд", "upload": "аплоуд",
    "install": "инсталл", "error": "эрор", "windowsupdate": "виндовс апдейт",
}

#: Как читаются латинские буквы (для сокращений и букв рядом с цифрами).
_LETTER_NAMES = {
    "a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи",
    "h": "эйч", "i": "ай", "j": "джей", "k": "кей", "l": "эл", "m": "эм",
    "n": "эн", "o": "оу", "p": "пи", "q": "кью", "r": "ар", "s": "эс", "t": "ти",
    "u": "ю", "v": "ви", "w": "дабл-ю", "x": "экс", "y": "уай", "z": "зэд",
}

#: Правила практической транскрипции английского (по-русски). Сканер берёт
#: САМОЕ ДЛИННОЕ совпадение в позиции, поэтому список сортируется по длине
#: образца: «ear» должно победить «ea» («hear» → «хир», а не «хеар»).
_RULES: tuple[tuple[str, str], ...] = (
    ("tion", "шн"), ("sion", "жн"), ("cion", "шн"), ("ture", "чер"), ("sure", "жер"),
    ("ight", "айт"), ("ought", "от"), ("augh", "аф"),
    ("sch", "ск"), ("chr", "кр"), ("tch", "ч"), ("dge", "дж"),
    ("air", "эр"), ("ear", "ир"), ("eer", "ир"), ("oor", "ор"), ("our", "ор"),
    ("iew", "ью"), ("ire", "айр"),
    ("ee", "и"), ("ea", "и"), ("ie", "и"), ("ei", "ей"), ("oo", "у"), ("ou", "ау"),
    ("ow", "оу"), ("oi", "ой"), ("oy", "ой"), ("au", "о"), ("aw", "о"), ("oa", "оу"),
    ("ai", "ей"), ("ay", "ей"), ("ey", "ей"), ("ue", "ю"), ("eu", "ью"), ("ui", "и"),
    ("ck", "к"), ("ch", "ч"), ("sh", "ш"), ("ph", "ф"), ("th", "т"), ("wh", "у"),
    ("qu", "кв"), ("gh", ""), ("kn", "н"), ("wr", "р"),
    ("ing", "инг"), ("ed", "ед"), ("es", "ес"), ("ate", "ейт"), ("ive", "ив"),
    ("ous", "ес"), ("ar", "ар"), ("er", "ер"), ("ir", "ир"), ("or", "ор"), ("ur", "ер"),
)

#: Подстановки до сканера: «магическая» конечная e (file → файл, name → нейм).
_PRE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"i([bcdfgklmnprstvz])e$"), r"ай\1"),
    (re.compile(r"a([bcdfgklmnprstvz])e$"), r"ей\1"),
    (re.compile(r"(?<=[bcdfgklmnprstvz])e$"), ""),
    (re.compile(r"^gh"), "г"),
)

_RULES = tuple(sorted(_RULES, key=lambda rule: -len(rule[0])))

_LATIN_RUN = re.compile(r"[A-Za-z]+(?:['’\-][A-Za-z]+)*")
_VOWELS = "aeiouy"

#: Единицы измерения и валюты: (формы 1/2..4/5+, женский род, «после числа»).
_UNITS: dict[str, tuple[tuple[str, str, str], bool, str]] = {
    "км/ч": (("километр в час", "километра в час", "километров в час"), False, ""),
    "км": (("километр", "километра", "километров"), False, ""),
    "см": (("сантиметр", "сантиметра", "сантиметров"), False, ""),
    "мм": (("миллиметр", "миллиметра", "миллиметров"), False, ""),
    "кг": (("килограмм", "килограмма", "килограммов"), False, ""),
    "мг": (("миллиграмм", "миллиграмма", "миллиграммов"), False, ""),
    "гб": (("гигабайт", "гигабайта", "гигабайтов"), False, ""),
    "мб": (("мегабайт", "мегабайта", "мегабайтов"), False, ""),
    "кб": (("килобайт", "килобайта", "килобайтов"), False, ""),
    "тб": (("терабайт", "терабайта", "терабайтов"), False, ""),
    "гц": (("герц", "герца", "герц"), False, ""),
    "кгц": (("килогерц", "килогерца", "килогерц"), False, ""),
    "мгц": (("мегагерц", "мегагерца", "мегагерц"), False, ""),
    "ггц": (("гигагерц", "гигагерца", "гигагерц"), False, ""),
    "вт": (("ватт", "ватта", "ватт"), False, ""),
    "квт": (("киловатт", "киловатта", "киловатт"), False, ""),
    "мин": (("минута", "минуты", "минут"), True, ""),
    "сек": (("секунда", "секунды", "секунд"), True, ""),
    "мс": (("миллисекунда", "миллисекунды", "миллисекунд"), True, ""),
    "шт": (("штука", "штуки", "штук"), True, ""),
    "руб": (("рубль", "рубля", "рублей"), False, ""),
    "₽": (("рубль", "рубля", "рублей"), False, ""),
    "$": (("доллар", "доллара", "долларов"), False, ""),
    "€": (("евро", "евро", "евро"), False, ""),
    "£": (("фунт", "фунта", "фунтов"), False, ""),
    "%": (("процент", "процента", "процентов"), False, ""),
    "°c": (("градус", "градуса", "градусов"), False, " цельсия"),
    "°f": (("градус", "градуса", "градусов"), False, " фаренгейта"),
    "°": (("градус", "градуса", "градусов"), False, ""),
    # Латинские написания единиц (ИИ часто отвечает «5 GB», «100 MHz») — иначе
    # транскрипция прочитала бы их по буквам («джи би»).
    "km": (("километр", "километра", "километров"), False, ""),
    "cm": (("сантиметр", "сантиметра", "сантиметров"), False, ""),
    "mm": (("миллиметр", "миллиметра", "миллиметров"), False, ""),
    "m": (("метр", "метра", "метров"), False, ""),
    "kg": (("килограмм", "килограмма", "килограммов"), False, ""),
    "mg": (("миллиграмм", "миллиграмма", "миллиграммов"), False, ""),
    "gb": (("гигабайт", "гигабайта", "гигабайтов"), False, ""),
    "mb": (("мегабайт", "мегабайта", "мегабайтов"), False, ""),
    "kb": (("килобайт", "килобайта", "килобайтов"), False, ""),
    "tb": (("терабайт", "терабайта", "терабайтов"), False, ""),
    "hz": (("герц", "герца", "герц"), False, ""),
    "khz": (("килогерц", "килогерца", "килогерц"), False, ""),
    "mhz": (("мегагерц", "мегагерца", "мегагерц"), False, ""),
    "ghz": (("гигагерц", "гигагерца", "гигагерц"), False, ""),
    "w": (("ватт", "ватта", "ватт"), False, ""),
    "kw": (("киловатт", "киловатта", "киловатт"), False, ""),
    "min": (("минута", "минуты", "минут"), True, ""),
    "sec": (("секунда", "секунды", "секунд"), True, ""),
    "ms": (("миллисекунда", "миллисекунды", "миллисекунд"), True, ""),
    "s": (("секунда", "секунды", "секунд"), True, ""),
    "h": (("час", "часа", "часов"), False, ""),
    "km/h": (("километр в час", "километра в час", "километров в час"), False, ""),
    "м/с": (("метр в секунду", "метра в секунду", "метров в секунду"), False, ""),
    "m/s": (("метр в секунду", "метра в секунду", "метров в секунду"), False, ""),
    "руб.": (("рубль", "рубля", "рублей"), False, ""),
    "rub": (("рубль", "рубля", "рублей"), False, ""),
}

_MONTHS_GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

#: «13:45» — часы и минуты (ровно как говорят: «тринадцать сорок пять»).
_RE_TIME = re.compile(r"(?<![\d.,])(\d{1,2}):([0-5]\d)(?![\d])")

#: Год со словом: «2026 год/году/года/г./гг».
_RE_YEAR_WORD = re.compile(r"(?<![\d.,])(\d{4})\s*(году|года|год|гг|г)\b\.?")
_YEAR_CASES = {
    "году": ("m", "pre"), "г": ("m", "pre"),
    "года": ("m", "gen"),
    "год": ("m", "nom"),
    "гг": ("pl", "nom"),
}

#: Год после предлога: «в 2026», «с 2020», «до 2024».
_RE_YEAR_PREPOSITION = re.compile(
    r"\b(в|во|с|со|до|от|к|ко|по)\s+(\d{4})(?![\d])", re.IGNORECASE
)
_PREPOSITION_CASES = {
    "в": ("m", "pre"), "во": ("m", "pre"),
    "с": ("m", "gen"), "со": ("m", "gen"), "до": ("m", "gen"), "от": ("m", "gen"),
    "к": ("m", "dat"), "ко": ("m", "dat"),
    "по": ("m", "nom"),
}

#: «5-й», «2-я», «3-го» — порядковые с суффиксом.
_RE_ORDINAL_SUFFIX = re.compile(
    r"(?<![\d.,])(\d+)\s*-\s*(й|я|е|ый|ой|ий|ые|го|ого|му|ому|м|х|ых|ом)\b",
    re.IGNORECASE,
)
_ORDINAL_SUFFIX_CASES = {
    "й": ("m", "nom"), "ый": ("m", "nom"), "ой": ("m", "nom"), "ий": ("m", "nom"),
    "я": ("f", "nom"), "е": ("n", "nom"), "ые": ("pl", "nom"),
    "го": ("m", "gen"), "ого": ("m", "gen"), "му": ("m", "dat"), "ому": ("m", "dat"),
    "м": ("m", "ins"), "ом": ("m", "pre"), "х": ("pl", "pre"), "ых": ("pl", "pre"),
}

#: Точки/запятые в числителе: дата «12.05.2026» или версия «3.12.1».
_RE_DOTTED = re.compile(r"(?<![\d.,])(\d{1,4})((?:[.,]\d{1,4})+)(?![\d])")

#: Единицы-множители, валюты и проценты рядом с числом. Длинные варианты в
#: альтернативе идут раньше коротких, а хвостовой lookahead не даёт «м»
#: поймать «мин», а «m» — «min»/«млн».
_RE_MEASURE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?: \d{3})+|\d+)(?:([.,])(\d+))?\s*"
    r"(км/ч|km/h|м/с|m/s|кгц|мгц|ггц|khz|mhz|ghz"
    r"|км|см|мм|кг|мг|гб|мб|кб|тб|мин|сек|мс|квт|шт|вт|гц"
    r"|km|cm|mm|kg|mg|gb|mb|kb|tb|min|sec|ms|kw|hz|rub"
    r"|руб\.?|₽|\$|€|£|%|°\s*[cfсф]|°|m|s|h|w)"
    r"(?![а-яёa-z0-9])",
    re.IGNORECASE,
)

#: Минус перед числом («-7 °C»): тире между цифрами — это диапазон «5-10»,
#: а дефис в «C-3PO» — часть слова, их не трогаем.
_RE_NEGATIVE = re.compile(r"(?<![\w.,-])-(?=\d)")

#: Простая дробь «1/2» — до того, как «/» станет пробелом.
_RE_FRACTION = re.compile(r"(?<![\d.,])(\d{1,3})/(\d{1,3})(?![\d])")

#: Любое оставшееся число: «1 500 000», «3,5», «-7». Знак «минус» берётся
#: только у отдельно стоящего числа: в «C-3PO» дефис — часть слова, а в
#: «5-10» — диапазон (иначе вышло бы «пять минус десять»).
_RE_NUMBER = re.compile(
    r"(?<!\d)((?<!\w)[+-])?(\d{1,3}(?: \d{3})+|\d+)(?:([.,])(\d+))?(?!\d)"
)

#: «—» (длинное тире) в наборе символов модели отсутствует: как и цифры, оно
#: молча исчезает и может склеить слова («привет—пока» → «приветпока»).
#: Заменяем на запятую — модель читает её как паузу, смысл сохраняется.
_RE_EM_DASH = re.compile(r"\s*—\s*")

#: Финальная страховка: всё, чего нет в наборе символов модели (эмодзи,
#: кавычки, скобки, остатки валют), вырезаем. Иначе символ просто исчезнет из
#: речи — и это невозможно заметить по коду синтеза.
_RE_UNREADABLE = re.compile(r"[^а-яёА-ЯЁ_~|!+,\-.:;?–…\s]")

#: Символы, которых нет в наборе символов модели, но которые несут смысл.
_SYMBOLS: tuple[tuple[str, str], ...] = (
    (r"[№#]", " номер "),
    (r"&", " и "),
    (r"@", " собака "),
    (r"=", " равно "),
    # «×» — однозначный знак умножения (латинскую «x» и кириллическую «х» не
    # трогаем: это буквы, «всех 5» не должно превращаться в «все на 5»).
    (r"×", " на "),
    (r"°\s*[cс]\b", " градусов цельсия "),
    (r"°\s*[fF]\b", " градусов фаренгейта "),
    (r"°", " градусов "),
    (r"%", " процентов "),
    (r"₽", " рублей "),
    (r"\$", " долларов "),
    (r"€", " евро "),
    (r"£", " фунтов "),
    (r"\bтыс\.", " тысяч "),
    (r"\bмлн\b", " миллионов "),
    (r"\bмлрд\b", " миллиардов "),
    # Остатки единиц без числа («одна вторая км/ч») — иначе «/» станет пробелом.
    (r"км/ч|km/h", " километров в час "),
    (r"м/с|m/s", " метров в секунду "),
    (r"[\\/]", " "),
)


# ── Числа ───────────────────────────────────────────────────────────


def _number_words(raw: str, feminine: bool = False) -> str:
    """«1 500» → «тысяча пятьсот», «3,5» → «три целых пять десятых»."""
    text = str(raw).strip().replace(" ", "")

    if not text:
        return ""

    if "." in text or "," in text:
        return decimal_to_words(text)

    try:
        return integer_to_words(int(text), feminine)
    except ValueError:
        return str(raw)


def _expand_dotted(text: str) -> str:
    """Даты и версии: «12.05.2026» → «двенадцатое мая … года», «3.12.1» → «… точка …»."""

    def repl(match: re.Match[str]) -> str:
        separator = match.group(2)[0]
        parts = re.split(r"[.,]", match.group(1) + match.group(2))

        if len(parts) == 2:
            if separator == ".":
                # Точка между цифрами — это техника, а не дробь: «Python 3.12»,
                # «v2.5». Дробь по-русски пишут запятой («3,5») — её раскроет
                # _expand_numbers словами («три целых пять десятых»).
                return f"{_number_words(parts[0])} точка {_number_words(parts[1])}"

            return match.group(0)

        try:
            numbers = [int(part) for part in parts]
        except ValueError:  # pragma: no cover — регулярка гарантирует цифры
            return match.group(0)

        day, month, year = numbers[0], numbers[1], numbers[2]

        if len(parts) == 3 and len(parts[2]) == 4 and 1900 <= year <= 2100 \
                and 1 <= day <= 31 and 1 <= month <= 12:
            return (
                f"{ordinal_to_words(day, 'n', 'nom')} {_MONTHS_GENITIVE[month - 1]} "
                f"{ordinal_to_words(year, 'm', 'gen')} года"
            )

        return " точка ".join(_number_words(str(number)) for number in numbers)

    return _RE_DOTTED.sub(repl, text)


def _expand_times(text: str) -> str:
    """«13:45» → «тринадцать сорок пять» (как это говорят вслух)."""

    def repl(match: re.Match[str]) -> str:
        hours, minutes = int(match.group(1)), int(match.group(2))

        if hours > 23:
            return match.group(0)

        if minutes == 0:
            return f"{_number_words(str(hours))} ноль ноль"

        lead = "ноль " if minutes < 10 else ""
        return f"{_number_words(str(hours))} {lead}{_number_words(str(minutes))}"

    return _RE_TIME.sub(repl, text)


def _expand_years(text: str) -> str:
    """«в 2026 году» → «в две тысячи двадцать шестом году»."""

    def with_word(match: re.Match[str]) -> str:
        year, word = int(match.group(1)), match.group(2).lower()
        gender, case = _YEAR_CASES.get(word, ("m", "nom"))

        if not 1000 <= year <= 2199:
            return match.group(0)

        suffix = "годы" if word == "гг" else word
        return f"{ordinal_to_words(year, gender, case)} {suffix}"

    def after_preposition(match: re.Match[str]) -> str:
        preposition, year = match.group(1).lower(), int(match.group(2))

        if not 1900 <= year <= 2100:
            return match.group(0)  # не год — раскроется как обычное число

        gender, case = _PREPOSITION_CASES.get(preposition, ("m", "nom"))
        return f"{preposition} {ordinal_to_words(year, gender, case)}"

    text = _RE_YEAR_WORD.sub(with_word, text)
    return _RE_YEAR_PREPOSITION.sub(after_preposition, text)


def _expand_ordinal_suffixes(text: str) -> str:
    """«5-й» → «пятый», «2-я» → «вторая», «3-го» → «третьего»."""

    def repl(match: re.Match[str]) -> str:
        number = int(match.group(1))
        suffix = match.group(2).lower()
        gender, case = _ORDINAL_SUFFIX_CASES.get(suffix, ("m", "nom"))
        return ordinal_to_words(number, gender, case)

    return _RE_ORDINAL_SUFFIX.sub(repl, text)


def _expand_fractions(text: str) -> str:
    """«1/2» → «одна вторая», «3/4» → «три четвёртых», «24/7» → «… седьмых»."""

    def repl(match: re.Match[str]) -> str:
        numerator, denominator = int(match.group(1)), int(match.group(2))

        if denominator < 2 or denominator > 10 or numerator == 0:
            return (
                f"{integer_to_words(numerator)} делить на "
                f"{integer_to_words(denominator)}"
            )

        # 1/2 — «одна вторая» (ж. р., ед. ч.), 2/3 — «две третьих» (мн. ч.).
        case = ("f", "nom") if numerator == 1 else ("pl", "gen")
        return (
            f"{integer_to_words(numerator, feminine=True)} "
            f"{ordinal_to_words(denominator, *case)}"
        )

    return _RE_FRACTION.sub(repl, text)


def _expand_measures(text: str) -> str:
    """«5%» → «пять процентов», «3,5 ГБ» → «три целых пять десятых гигабайта»."""

    def repl(match: re.Match[str]) -> str:
        whole = match.group(1).replace(" ", "")
        separator = match.group(2) or ""
        fraction = match.group(3) or ""
        # «°С» пишут и кириллицей — приводим к ключам таблицы (только сам знак
        # градуса: в «см»/«кг» кириллица остаётся кириллицей).
        unit_key = re.sub(r"\s+", "", match.group(4)).lower()
        if unit_key.startswith("°"):
            unit_key = "°" + unit_key[1:].replace("с", "c").replace("ф", "f")

        unit = _UNITS.get(unit_key)

        if unit is None:
            return match.group(0)

        forms, feminine, tail = unit

        if separator and fraction:
            words = decimal_to_words(f"{whole}{separator}{fraction}")
            # У дробей существительное всегда в родительном: «1,5 килограмма».
            return f"{words} {forms[1]}{tail}"

        value = int(whole or 0)
        words = integer_to_words(value, feminine)
        return f"{words} {agree(value, forms)}{tail}"

    return _RE_MEASURE.sub(repl, text)


def _expand_numbers(text: str) -> str:
    """Оставшиеся числа: «1 500» → «тысяча пятьсот», «-7» → «минус семь»."""

    def repl(match: re.Match[str]) -> str:
        sign = match.group(1)
        whole = match.group(2).replace(" ", "")
        separator = match.group(3) or ""
        fraction = match.group(4) or ""

        raw = f"-{whole}" if sign == "-" else whole

        if separator and fraction:
            raw = f"{raw}{separator}{fraction}"

        words = _number_words(raw)

        # Число, приклеенное к слову («тест2»), отделяем пробелом.
        previous = text[match.start() - 1] if match.start() else ""
        prefix = " " if previous.isalnum() else ""
        return f"{prefix}{words}"

    return _RE_NUMBER.sub(repl, text)


def expand_numbers(text: str) -> str:
    """Раскрывает в тексте всё числовое: даты, время, годы, единицы, числа."""
    if not text:
        return text

    result = text.replace("\u00a0", " ")
    result = _RE_NEGATIVE.sub("минус ", result)
    result = _expand_dotted(result)
    result = _expand_times(result)
    result = _expand_years(result)
    result = _expand_ordinal_suffixes(result)
    result = _expand_fractions(result)
    result = _expand_measures(result)
    return _expand_numbers(result)


# ── Латиница ────────────────────────────────────────────────────────


def _spell(word: str) -> str:
    """Читает сокращение по буквам: «CS2» → «си эс», «v» → «ви»."""
    return " ".join(_LETTER_NAMES[char] for char in word.lower() if char in _LETTER_NAMES)


def _transcribe(word: str) -> str:
    """Практическая транскрипция английского слова кириллицей."""
    for pattern, replacement in _PRE_RULES:
        word = pattern.sub(replacement, word)

    out: list[str] = []
    index = 0
    length = len(word)

    while index < length:
        char = word[index]

        if not "a" <= char <= "z":
            out.append(char)  # уже кириллица из подстановок выше
            index += 1
            continue

        for pattern, replacement in _RULES:
            if word.startswith(pattern, index):
                out.append(replacement)
                index += len(pattern)
                break
        else:
            out.append(_fallback(word, index))
            index += 1

    return "".join(out)


def _fallback(word: str, index: int) -> str:
    """Одиночная буква — с учётом позиции (c/g перед e,i,y; w перед гласной)."""
    char = word[index]
    following = word[index + 1] if index + 1 < len(word) else ""

    if char == "c":
        return "с" if following in "eiy" else "к"
    if char == "g":
        return "дж" if following in "eiy" else "г"
    if char == "w":
        return "у" if following in _VOWELS else "в"
    if char == "y":
        return "й" if index == 0 else "и"
    if char == "e":
        return "э" if index == 0 else "е"

    return {
        "a": "а", "b": "б", "d": "д", "f": "ф", "h": "х", "i": "и", "j": "дж",
        "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "q": "к",
        "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "x": "кс", "z": "з",
    }.get(char, "")


def _transcribe_run(match: re.Match[str]) -> str:
    """Одно латинское слово: словарь → буквы → правила."""
    token = match.group(0)
    lower = token.lower()

    if lower in _WORDS:
        return _WORDS[lower]

    # «°C»/«°F» — это не буква, а знак шкалы: «65 °C» = «шестьдесят пять
    # градусов цельсия» (пару «число + °C» до этого съедает таблица единиц).
    if match.start() and match.string[match.start() - 1] == "°":
        scale = {"c": "цельсия", "f": "фаренгейта"}.get(lower)
        if scale:
            return scale

    # Дефис/апостроф внутри слова читаются как пауза: «wi-fi» → «ви фи».
    parts = re.split(r"[-'’]", token)
    if len(parts) > 1:
        return " ".join(_transcribe_run_part(part) for part in parts if part)

    next_char = match.string[match.end():match.end() + 1]

    if token.isupper() and 2 <= len(token) <= 6:
        return _spell(token)  # «CS2» → «си эс», «GTX» → «джи ти экс»

    if next_char.isdigit() and len(token) <= 3:
        return _spell(token)  # «mp3» → «эм пи», «v5» → «ви»

    if len(token) == 1:
        return _spell(token)

    return _transcribe(lower)


def _transcribe_run_part(token: str, spelled: bool = False) -> str:
    """Транскрипция куска латинского токена (после разбиения по дефису)."""
    if token.lower() in _WORDS:
        return _WORDS[token.lower()]

    return _spell(token) if (spelled or token.isupper()) else _transcribe(token.lower())


def transliterate_latin(text: str) -> str:
    """Заменяет латинские слова кириллицей (словарь + правила транскрипции)."""
    if not text:
        return text

    return _LATIN_RUN.sub(_transcribe_run, text)


# ── Общий проход ────────────────────────────────────────────────────


def _replace_symbols(text: str) -> str:
    for pattern, replacement in _SYMBOLS:
        text = re.sub(pattern, replacement, text)

    return text


def normalize(text: str) -> str:
    """Готовит текст для русской модели Silero v5_5_ru.

    После нормализации в строке не остаётся ничего, чего модель не прочла бы
    молча-выбрасывая: ни латиницы, ни цифр, ни эмодзи с кавычками.

    >>> normalize("В 2026 году вышел Python 3.12 на 5 ГБ")
    'В две тысячи двадцать шестом году вышел Питон три точка двенадцать на пять гигабайтов'
    """
    if not text:
        return text

    # Порядок важен. Сначала единицы/проценты/валюты: «5 GB» и «65 °C» — это
    # число с единицей, а не число и латинское слово («джи би»). Потом
    # латиница (уже без чисел-с-единицами): «mp3» читается по буквам, пока
    # цифра ещё приклеена к слову. Потом всё остальное числовое и символы.
    result = _RE_NEGATIVE.sub("минус ", text)
    result = _expand_fractions(result)
    result = _expand_measures(result)
    result = transliterate_latin(result)
    result = expand_numbers(result)
    result = _replace_symbols(result)
    result = _RE_EM_DASH.sub(", ", result)
    result = _RE_UNREADABLE.sub("", result)

    return re.sub(r"\s{2,}", " ", result).strip()
