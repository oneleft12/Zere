"""Выбор устройства ввода/вывода для sounddevice (PortAudio).

Зачем это нужно. По умолчанию sounddevice берёт устройство из бэкенда **MME**
(Windows Multimedia, 1991): его ресемплер портит звук даже при совпадении
частот, а буфер — 180 мс. Замеры на Sennheiser USB headset (44100 Гц):

    MME          latency 0.180 c
    DirectSound  latency 0.240 c
    WASAPI       latency 0.022 c   <-- выбираем его
    WDM-KS       blocking API не поддерживается

Поэтому здесь ищется то же физическое устройство (по имени) в бэкенде WASAPI
(`sd.WasapiSettings()`), а если его нет — возвращается значение по умолчанию,
как было раньше: голос не должен пропадать из-за отсутствия WASAPI.

Второй слой той же проблемы — частота. WASAPI в shared-режиме принимает
только частоту микшера Windows, а микрофон/STT живут на 16 кГц: без флага
`paWinWasapiAutoConvert` открытие падает с

    Error opening InputStream: Invalid sample rate [PaErrorCode -9997]

Поэтому наружу отдаются не «индексы устройств», а готовые наборы аргументов
(`input_options`/`output_options`): WASAPI с системным ресемплером, а если
вариант не поддержан — устройство по умолчанию (MME, PortAudio ресемплирует
сам). Подробности и живые замеры — в докстринге `input_options`.
"""

from __future__ import annotations

from typing import Any, Optional

import sounddevice as sd

# Имя бэкенда PortAudio, который считаем предпочтительным.
_PREFERRED_HOSTAPI = "Windows WASAPI"


def _hostapi_name(index: int) -> str:
    """Имя hostapi по индексу устройства/бэкенда; пустая строка при ошибке."""
    try:
        return str(sd.query_hostapis(index)["name"])
    except Exception:  # noqa: BLE001 — нет бэкенда/PortAudio
        return ""


def preferred_hostapi_index() -> Optional[int]:
    """Индекс предпочтительного бэкенда (WASAPI) или None, если его нет."""
    try:
        for index, api in enumerate(sd.query_hostapis()):
            if api["name"] == _PREFERRED_HOSTAPI:
                return index
    except Exception:  # noqa: BLE001 — PortAudio недоступен
        return None

    return None


def _same_device(default_name: str, candidate: str) -> bool:
    """Совпадают ли имена одного устройства в разных бэкендах.

    Имена сравнивать «в лоб» нельзя: MME обрезает название до 31 символа
    (`'…Sennheiser USB headse'`), а WASAPI отдаёт полное
    (`'…Sennheiser USB headset'`). Поэтому сравниваем по префиксу —
    обрезанное MME-имя всегда является префиксом полного.
    """
    short, long = (default_name, candidate) if len(default_name) <= len(candidate) \
        else (candidate, default_name)

    # Слишком короткое имя (например «Output») даст ложные совпадения.
    if len(short) < 12:
        return default_name == candidate

    return long.startswith(short) or short.startswith(long)


def resolve_device(kind: str, fallback: Any = None) -> Any:
    """Устройство `kind` ("output"/"input") в бэкенде WASAPI.

    Ищем в WASAPI устройство с тем же именем, что и устройство по умолчанию —
    это та же физическая гарнитура, но с нормальным трактом. Если не нашли
    (или WASAPI нет), возвращаем `fallback` (по умолчанию — None, то есть
    обычное поведение sounddevice с MME).
    """
    default = sd.default.device

    # sd.default.device = (вход, выход); индекс 1 — вывод, 0 — ввод.
    default_index = default[1] if kind == "output" else default[0]

    if default_index is None or default_index < 0:
        return fallback

    try:
        default_name = str(sd.query_devices(default_index)["name"])
        wasapi_index = preferred_hostapi_index()

        if wasapi_index is None:
            return fallback

        channels_key = "max_output_channels" if kind == "output" else "max_input_channels"

        for index, device in enumerate(sd.query_devices()):
            if device["hostapi"] != wasapi_index:
                continue

            if device[channels_key] <= 0:
                continue

            if _same_device(default_name, str(device["name"])):
                return index
    except Exception:  # noqa: BLE001 — любая ошибка PortAudio = обычное поведение
        return fallback

    return fallback


def output_device() -> Any:
    """Устройство вывода: WASAPI-аналог устройства по умолчанию, иначе None."""
    return resolve_device("output")


def input_device() -> Any:
    """Устройство ввода: WASAPI-аналог устройства по умолчанию, иначе None."""
    return resolve_device("input")


# ─── Частота потока и откат: почему 16 кГц не открывались на WASAPI ───


def _wasapi_settings() -> Optional[Any]:
    """WasapiSettings с системным ресемплером (флаг paWinWasapiAutoConvert).

    Без этого флага WASAPI в shared-режиме принимает только *микшерную*
    частоту Windows. `None` — sounddevice старый или подменён заглушкой:
    тогда вариант идёт без `extra_settings`, а от -9997 подстрахует откат
    на устройство по умолчанию (MME).
    """
    factory = getattr(sd, "WasapiSettings", None)

    if factory is None:
        return None

    try:
        return factory(auto_convert=True)
    except Exception:  # noqa: BLE001 — старый sounddevice/битая сборка PortAudio
        return None


def _candidates(device: Any) -> list[dict[str, Any]]:
    """Варианты открытия потока в порядке предпочтения.

    1. WASAPI как есть — если запрошенная частота совпала с микшерной,
       системный ресемплер не подключается вовсе (самый короткий тракт);
    2. WASAPI + `auto_convert` — системный ресемплер Windows приводит частоту
       (16 кГц против микшера 44.1/48 кГц; без флага — -9997);
    3. MME (устройство по умолчанию): PortAudio ресемплирует сам, поэтому
       любая частота здесь открывается — это и есть страховка.
    """
    options: list[dict[str, Any]] = []

    if device is not None:
        options.append({"device": device})

        settings = _wasapi_settings()

        if settings is not None:
            options.append({"device": device, "extra_settings": settings})

    options.append({"device": None})

    return options


def _first_supported(options: list[dict[str, Any]], check: Any) -> dict[str, Any]:
    """Первый вариант, который PortAudio считает поддерживаемым.

    Проверка идёт без открытия потока (`check_input_settings` /
    `check_output_settings`), поэтому перебор бесплатный. Если не подошёл ни
    один — возвращаем последний (устройство по умолчанию): пусть попытка
    открытия произойдёт, а ошибка будет видна вызывающему коду.
    """
    if check is None:
        # Заглушка вместо sounddevice (CI/тесты без PortAudio): берём
        # предпочтительный вариант — с auto_convert он рабочий.
        return options[0]

    for option in options:
        try:
            check(**option)
            return option
        except Exception:  # noqa: BLE001 — вариант не поддержан, берём следующий
            continue

    return options[-1]


def input_options(
    samplerate: int, channels: int = 1, dtype: str = "int16"
) -> dict[str, Any]:
    """Аргументы открытия входа (`device`/`extra_settings`) для нужной частоты.

    Зачем: порт на sounddevice перешёл на WASAPI (низкая задержка), но WASAPI
    в shared-режиме принимает только частоту микшера Windows. Микрофон
    Sennheiser USB headset заявляет 48 кГц, микшер работает на 44.1 кГц, а
    Whisper/GigaAM требуют 16 кГц — без `auto_convert` PortAudio падает:

        Error opening InputStream: Invalid sample rate [PaErrorCode -9997]

    Живые замеры (Windows 11, Sennheiser USB headset, WASAPI-устройство 27,
    sounddevice 0.5.6):

        check_input_settings(27, 16000)                     → -9997
        check_input_settings(27, 16000, auto_convert=True)  → OK
        check_input_settings(27, 48000)                     → OK

    Флаг разрешает системному ресемплеру Windows привести частоту, поэтому
    WASAPI остаётся (22 мс против 180 мс у MME), а 16 кГц снова открываются.
    Если WASAPI-вариант не поддержан, возвращается устройство по умолчанию
    (MME): голос не должен пропадать из-за WASAPI.
    """
    check = getattr(sd, "check_input_settings", None)

    def supported(**option: Any) -> None:
        check(samplerate=samplerate, channels=channels, dtype=dtype, **option)

    return _first_supported(
        _candidates(input_device()), supported if check is not None else None
    )


def output_options(
    samplerate: int, channels: int = 1, dtype: str = "float32"
) -> dict[str, Any]:
    """Аргументы открытия вывода: та же логика, что у `input_options`.

    Озвучка ресемплится под частоту устройства по умолчанию (MME-частота), а
    у WASAPI-устройства микшерная частота может быть другой — без
    `auto_convert` PortAudio вернёт ту же -9997, только уже на `OutputStream`.
    """
    check = getattr(sd, "check_output_settings", None)

    def supported(**option: Any) -> None:
        check(samplerate=samplerate, channels=channels, dtype=dtype, **option)

    return _first_supported(
        _candidates(output_device()), supported if check is not None else None
    )
