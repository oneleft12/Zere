"""ZERE — точка входа (Python-порт ZERE.App/Program.cs)."""

from __future__ import annotations

import os
import sys
import threading
import webbrowser

# Лёгкий модуль без зависимостей: он нужен до импорта тяжёлых пакетов,
# чтобы сбой импорта попал в logs\desktop.log (у pythonw нет stderr).
from zere.desktop.startup_log import log_startup_failure

try:
    from zere import paths
    from zere.ai.ai_service import AiService
    from zere.ai.ai_settings import AiSettings
    from zere.api.server import DEFAULT_PORT, PanelServer
    from zere.core.configuration.zere_config import ZereConfig
    from zere.core.console import configure_console_encoding
    from zere.core.context.runtime_context import RuntimeContext
    from zere.core.dependencies.dependency_checker import DependencyChecker
    from zere.core.engine import ZereEngine
    from zere.core.logging.log_service import LogService
    from zere.core.plugins.plugin_config import PluginConfig
    from zere.core.plugins.plugin_manager import PluginManager
    from zere.core.plugins.settings.settings_menu import SettingsMenu
    from zere.core.services import create_services
    from zere.desktop.desktop import desktop_requested, port_from_argv, run_desktop
    from zere.desktop.stdio import ensure_std_streams
    from zere.desktop.window import PanelWindowHost
    from zere.memory.database.conversation_repository import ConversationRepository
    from zere.memory.database.memory_database import MemoryDatabase
    from zere.memory.database.memory_repository import MemoryRepository
    from zere.tools.applications.application_launcher import ApplicationLauncher
    from zere.tools.files.file_manager import FileManager
    from zere.tools.windows.process_service import ProcessService
    from zere.tools.windows.safe_action_manager import SafeActionManager
    from zere.voice.voice_bootstrap import bootstrap_voice
    from zere.voice.voice_manager import VoiceManager
except BaseException as _import_error:  # noqa: BLE001 — фиксируем и пробрасываем
    # Только для запуска без консоли: при обычном `python main.py` traceback и
    # так виден в терминале, но запись в журнал не мешает.
    log_startup_failure(_import_error)
    raise


_USAGE = """ZERE — персональный AI-ассистент.

Запуск:
  zere.exe                 — приложение (окно, без консоли)
  python main.py --desktop — то же, без лаунчера
  python main.py           — консольный режим (отладка)

Флаги:
  --desktop, --app, --gui  приложение: окно поверх локальной панели
  --port N                 порт панели (по умолчанию 8080)
  --console                консольный режим (так лаунчер запускает отладку)
  --help                   эта справка
"""


def main() -> int:
    argv = sys.argv[1:]

    # Рабочий каталог — корень ZERE, как у лаунчера zere.exe. При автозапуске
    # через HKCU\...\Run Windows не задаёт рабочий каталог (процесс стартует
    # из System32), а часть кода (метка сборки для обновлений) читает
    # относительные пути. Сбой chdir не критичен: пути приложения абсолютные.
    try:
        os.chdir(paths.PROJECT_ROOT)
    except OSError:
        pass

    if any(argument in ("--help", "-h") for argument in argv):
        print(_USAGE)
        return 0

    # Режим приложения: консоли нет, окно рисует pywebview (WebView2).
    desktop = desktop_requested(argv)

    # pythonw.exe (так запускает zere.exe) не имеет stdout/stderr: у процесса
    # это None. Без подмены диагностика старта исчезает, а flush() падает.
    if desktop:
        ensure_std_streams(paths.desktop_log_path())

    # Эмодзи в принтах при перенаправленном выводе (cp866/cp1251) падали
    # UnicodeEncodeError — в аудио-пути это выглядело как сбой микрофона.
    configure_console_encoding()

    config = ZereConfig.load()
    logger = LogService()

    logger.info(f"{config.assistant_name} OS {config.version} запускается.")

    # Очистка voice/input/ при каждом запуске (ROADMAP 1.3)
    _cleanup_voice_input()

    print(f"""
=================================
        {config.assistant_name}
=================================

Версия: {config.version}
Модель: {config.model}
Язык: {config.language}

""")

    # Облачный ключ (config/ai.json или окружение владельца) делает Ollama
    # необязательной: ZERE стартует и отвечает через облачную модель.
    cloud_available = AiSettings.load().has_key()
    checker = DependencyChecker(config, cloud_available=cloud_available)
    checker.run_all()
    checker.print_report()

    if not checker.all_critical_passed():
        if desktop:
            # В приложении некому отвечать на «Нажмите Enter» и предустановки
            # не запустить: панель сама показывает «Подключение ИИ», поэтому
            # старт не блокируем — приложение открывается и предлагает настройку.
            print("Критические зависимости не выполнены — настройка через панель → «ИИ».")
        else:
            checker.offer_install()

            if not checker.all_critical_passed():
                print("Критические зависимости не выполнены.")
                if cloud_available:
                    print("Настроен облачный API-ключ — он используется приоритетно.")
                print("Откройте панель → «ИИ»: введите API-ключ или установите локальную модель.")
                print("Устраните ошибки выше и запустите снова.")
                print("Нажмите Enter для выхода...")
                try:
                    input()
                except EOFError:
                    pass
                return 1

    if checker.all_critical_passed():
        print("Все зависимости в порядке.\n")
    else:
        # Сюда доходит только режим приложения: в консоли выше стоит return 1.
        # ZERE без Ollama и без облачного ключа всё равно запускается — окно и
        # панель работают, ИИ настраивается на экране «ИИ».
        print("ИИ не настроен: ZERE работает, укажите ключ или модель в панели → «ИИ».\n")

    # Предложить установку голосовых компонентов (не критичные). В приложении
    # спрашивать некого — установка голоса остаётся за installer\install.ps1.
    if config.voice_enabled and not desktop:
        checker.offer_voice_install()

    services = create_services(config)

    services.get(MemoryDatabase)

    zere = services.get(ZereEngine)
    voice_manager = VoiceManager()

    # Локальная панель (этап 1 GUI-плана): loopback + токен, контракт
    # docs/api/openapi.yaml. Сбой порта не должен ронять консоль.
    panel = PanelServer(
        engine=zere,
        config=services.get(ZereConfig),
        memory=services.get(MemoryRepository),
        conversation=services.get(ConversationRepository),
        plugin_config=services.get(PluginConfig),
        process_service=services.get(ProcessService),
        safe_actions=services.get(SafeActionManager),
        app_launcher=services.get(ApplicationLauncher),
        # Поиск папок и открытие в проводнике — тот же FileManager, что
        # отвечает на команды чата (общий кэш индекса).
        files=services.get(FileManager),
        voice=voice_manager,
        # Голосовой режим из панели: AIHandler отвечает коротко, пока
        # цикл /api/voice/mode жив (тот же синглтон, что и в консоли).
        runtime=services.get(RuntimeContext),
        # Настройки ИИ: облачный ключ пользователя / локальная модель —
        # тот же сервис, что отвечает в чате (единый выбор провайдера).
        ai=services.get(AiService),
        # Порт панели: у приложения и консоли один контракт, но тестам и
        # второму окну нужен другой порт (--port 8081).
        port=port_from_argv(argv, DEFAULT_PORT),
    )
    # URL панели для команды «панель»; None — сервер не поднялся (только
    # консольный режим: в приложении сервер поднимает run_desktop).
    panel_url: str | None = None

    if not desktop:
        # Консольный режим — отладка: панель открывается в браузере. Окно
        # приложения поднимает desktop-режим (zere.exe) на главном потоке.
        try:
            panel.start()
            panel_url = f"http://127.0.0.1:{panel.port}"
            print(f"[Панель] {panel_url} (токен: config/panel.token)")
            _open_panel_in_browser(panel_url, logger)
        except OSError as ex:
            logger.error(f"PanelServer: {ex}")
            print("[Панель] Не удалось запустить локальный сервер (порт занят?).")

    # Громкость голоса из config.json (voiceVolume, дефолт 0.5)
    voice_manager.config.volume = float(config.voice_volume)

    # Движок распознавания речи из config.json (sttEngine, дефолт gigaam)
    voice_manager.config.stt_engine = str(config.stt_engine)

    # Движок синтеза речи из config.json (ttsEngine: silero; pocket — только C#).
    # Смена движка в панели требует перезапуска — как и написано на экране.
    voice_manager.config.tts_engine = str(config.tts_engine)

    # Слово-триггер из config.json (wake*): движок (auto | kws | whisper),
    # путь к ONNX-модели, порог/сглаживание/cooldown и отсечка тишины.
    # Пустые значения = значения из манифеста модели. Подробности: docs/WAKE_WORD.md.
    voice_manager.config.wake_engine = str(config.wake_engine)
    voice_manager.config.wake_model_path = str(config.wake_model_path)
    voice_manager.config.wake_threshold = float(config.wake_threshold)
    voice_manager.config.wake_min_consecutive = int(config.wake_min_consecutive)
    voice_manager.config.wake_cooldown_ms = int(config.wake_cooldown_ms)
    voice_manager.config.wake_energy_gate = bool(config.wake_energy_gate)

    # DSP-обработка озвучки из config.json (audioProcessing, дефолт true):
    # читается на каждое предложение — переключается из панели на лету
    voice_manager.config.audio_processing = bool(config.audio_processing)

    active_personality = zere.plugin_manager.active_personality
    if active_personality is not None:
        print(f"[Личность] {active_personality.name} | Стиль: {active_personality.style}\n")

    # Прогрев локальной модели в фоне (этап 1, анализ S5): первый
    # «настоящий» запрос не платит за загрузку модели; keep_alive из
    # конфига удерживает её в памяти. Если выбран облачный провайдер,
    # прогрева нет; ошибки не критичны.
    def _warmup_llm() -> None:
        try:
            client = services.get(AiService).proxy
            if client is not None:
                client.warmup()
        except Exception as ex:  # noqa: BLE001 — прогрев не должен мешать старту
            logger.error(f"Warmup: {ex}")

    # TTS поднимаем всегда, в том числе при выключенном голосовом выводе:
    # панель тестирует синтез («Озвучить» на экране «Голос»), а initialize()
    # только проверяет окружение (веса грузятся при первом синтезе).
    # Предзагрузка STT — признак включённого голоса: она качает модель.
    def _bootstrap_voice() -> None:
        bootstrap_voice(
            voice_manager,
            voice_enabled=bool(config.voice_enabled),
            personality_style=str(active_personality.style) if active_personality else None,
            # Предзагрузка STT в фоне (ROADMAP 1.3): не блокируем старт;
            # для GigaAM здесь же качается модель (~163 МБ), если её ещё нет
            start_stt_preload=lambda: threading.Thread(
                target=voice_manager.preload_stt,
                daemon=True,
            ).start(),
        )

        if config.voice_enabled:
            print("[Голос] Режим: текст + голос")
        else:
            print("[Голос] Отключен. Только текстовый режим.")

        threading.Thread(target=_warmup_llm, daemon=True).start()

    # Режим приложения: окно открывается сразу, а голос и прогрев модели —
    # после старта GUI (pywebview зовёт on_ready в своём потоке). Иначе
    # пользователь ждёт загрузку TTS/STT, глядя на пустой рабочий стол.
    if desktop:
        def _on_ready() -> None:
            try:
                _bootstrap_voice()
            except Exception as ex:  # noqa: BLE001 — голос не должен гасить окно
                logger.error(f"Desktop start: {ex}")

        print(f"Команды: приложение, панель {panel.port}; выход — закрыть окно.")
        return run_desktop(
            panel=panel,
            voice=voice_manager,
            logger=logger,
            on_ready=_on_ready,
            icon=paths.icon_path(),
            storage_path=paths.webview_dir(),
        )

    _bootstrap_voice()

    # Флаги рантайма: voice_mode → AIHandler отвечает коротко (этап 1, S5)
    runtime = services.get(RuntimeContext)

    print("Команды: 'настройки' — панель настроек, 'exit' — выход")
    print("         'панель' / 'panel' — открыть окно панели")
    print("         'голос' / 'voice' — переключить голосовой режим\n")

    voice_mode = False

    while True:
        if voice_mode:
            if runtime is not None:
                runtime.voice_mode = True

            run_voice_mode(voice_manager, zere, config, logger, [True])

            if runtime is not None:
                runtime.voice_mode = False

            voice_mode = False
            # Вышли из голосового режима → детектор и микрофон
            # освобождаются (общий Whisper переиспользуется, анализ S3).
            voice_manager.disable_wake_word()
            continue

        try:
            message = input("Вы: ")
        except EOFError:
            break

        if not message or not message.strip():
            continue

        lowered = message.strip().lower()

        if lowered == "exit":
            break

        if lowered in ("настройки", "settings"):
            plugin_manager = services.get(PluginManager)
            plugin_config = services.get(PluginConfig)

            settings_menu = SettingsMenu(plugin_manager, plugin_config)
            settings_menu.show()

            active_personality = zere.plugin_manager.active_personality
            if active_personality is not None:
                print(f"\n[Личность] {active_personality.name} | Стиль: {active_personality.style}\n")

                if config.voice_enabled:
                    voice_manager.set_personality_voice(str(active_personality.style))
            continue

        if lowered in ("панель", "panel"):
            if panel_url is not None:
                _open_panel_window(panel_url, logger)
            else:
                print("[Панель] Сервер не запущен — команда недоступна.")
            continue

        if lowered in ("голос", "voice"):
            if not config.voice_enabled:
                print("\nГолос отключен в конфиге.\n")
                continue

            voice_mode = True
            print("\n[Голос] Голосовой режим активирован. Скажите 'выход' для отключения.\n")
            continue

        try:
            answer = zere.process(message)

            logger.info(f"ZERE: {answer}")

            print()
            print(f"ZERE: {answer}")
            print()

            if config.voice_enabled:
                voice_manager.speak(answer)
        except Exception as ex:  # noqa: BLE001 — как в исходнике: ловим всё
            logger.error(str(ex))

            print()
            print(f"Ошибка: {ex}")
            print()

    panel.stop()
    voice_manager.close()
    logger.info("ZERE завершил работу.")
    return 0


def _open_panel_in_browser(url: str, logger: LogService) -> None:
    """Открывает панель в браузере (этап 5): сбой браузера не роняет консоль."""
    try:
        webbrowser.open(url)
        print(f"[Панель] Открыта в браузере: {url}")
    except Exception as ex:  # noqa: BLE001 — браузер может быть недоступен вовсе
        logger.error(f"PanelBrowser: {ex}")
        print(f"[Панель] Браузер не открылся — вручную: {url}")


_panel_window_lock = threading.Lock()
_panel_window_host: PanelWindowHost | None = None


def _open_panel_window(url: str, logger: LogService) -> None:
    """Показывает панель окном приложения (команда «панель» в консоли).

    Окно живёт в фоновом потоке: главный занят чтением команд. pywebview в
    этом режиме может отказать — он ставит обработчик SIGINT, а это разрешено
    только главному потоку; тогда PanelWindowHost честно открывает панель в
    браузере, как было до появления окна.
    """
    global _panel_window_host

    with _panel_window_lock:
        if _panel_window_host is None:
            _panel_window_host = PanelWindowHost(
                url,
                logger,
                icon=paths.icon_path(),
                storage_path=paths.webview_dir(),
                on_failure=lambda failed_url: _open_panel_in_browser(failed_url, logger),
            )

    _panel_window_host.open()


def _cleanup_voice_input() -> None:
    """Удаляет накопленные voice/input/*.wav при каждом запуске (ROADMAP 1.3)."""
    input_dir = paths.voice_dir() / "input"
    if not input_dir.is_dir():
        return

    for file_path in input_dir.glob("*.wav"):
        try:
            file_path.unlink()
        except OSError:
            pass  # очистка не должна ронять старт


def _text_fallback(voice_manager: VoiceManager, zere: ZereEngine, config: ZereConfig, logger: LogService, keep_running: list[bool]) -> None:
    """Fallback «Whisper не отвечает → текстовый ввод» (ROADMAP 1.1):
    предлагает ввести команду текстом, не выходя из голосового режима.
    """
    print("⚠️ Не удалось распознать команду.")
    try:
        text_input = input("Введите команду текстом (Enter — в спящий режим): ").strip()
    except EOFError:
        text_input = ""

    if not text_input:
        return

    if text_input.lower() in ("выход", "стоп", "exit"):
        keep_running[0] = False
        print("[Голос] Текстовый режим.\n")
        return

    _process_voice(text_input, zere, config, logger, voice_manager)


def run_voice_mode(
    voice_manager: VoiceManager,
    zere: ZereEngine,
    config: ZereConfig,
    logger: LogService,
    keep_running: list[bool],
) -> None:
    """Голосовой режим: wake word + голосовые команды (порт ветки voiceMode)."""
    try:
        import msvcrt  # noqa: PLC0415 — Windows-only, как и весь проект
    except ImportError:
        msvcrt = None  # type: ignore[assignment]

    while keep_running[0]:
        if voice_manager.config.wake_word_enabled:
            voice_manager.enable_wake_word()

            print(f"\n💤 Спящий режим. Скажите '{voice_manager.config.wake_word}' для активации.")
            print("   Или напишите 'выход' для отключения голосового режима.\n")

            cancel_event = threading.Event()

            wake_result: list[bool] = [False]
            wake_error: list[BaseException] = []

            def wake_worker(
                cancel: threading.Event,
                result: list[bool],
                errors: list[BaseException],
            ) -> None:
                try:
                    result[0] = voice_manager.wait_for_wake_word(cancel)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            wake_thread = threading.Thread(
                target=wake_worker,
                args=(cancel_event, wake_result, wake_error),
                daemon=True,
            )
            wake_thread.start()

            aborted = False
            while wake_thread.is_alive() and not cancel_event.is_set():
                # Неблокирующая проверка консоли (Console.KeyAvailable → msvcrt)
                if msvcrt is not None and msvcrt.kbhit():
                    text_input = input().strip().lower()
                    if text_input in ("выход", "стоп", "exit"):
                        cancel_event.set()
                        break
                wake_thread.join(timeout=0.1)

            cancel_event.set()
            wake_thread.join()

            if cancel_event.is_set() and not wake_result[0] and not wake_error:
                # Пользователь ввёл 'выход' — выходим из голосового режима
                aborted = True

            if aborted:
                keep_running[0] = False
                print("\n[Голос] Текстовый режим.\n")
                return

            if wake_error or not wake_result[0]:
                if wake_error:
                    keep_running[0] = False
                    print("\n[Голос] Текстовый режим.\n")
                    return
                continue

            # Ключевое слово обнаружено!
            print("\n🎧 Слушаю вашу команду...")
            print("   (или напишите 'выход')\n")

            voice_input = voice_manager.listen_command()

            if not voice_input or not voice_input.strip():
                print("⚠️ Не удалось распознать команду.\n")
                _text_fallback(voice_manager, zere, config, logger, keep_running)
                if not keep_running[0]:
                    return
                print("💤 Возвращаюсь в спящий режим.\n")
                continue

            print(f"Вы (голос): {voice_input}\n")

            if voice_input.strip().lower() in ("выход", "стоп"):
                keep_running[0] = False
                print("[Голос] Текстовый режим.\n")
                return

            _process_voice(voice_input, zere, config, logger, voice_manager)
            print("💤 Возвращаюсь в спящий режим.\n")
        else:
            # Обычный режим без ключевого слова (старый вариант)
            print("[ГОЛОС] Скажите команду... ")
            voice_input = voice_manager.listen()

            if not voice_input or not voice_input.strip():
                print("Не удалось распознать речь.")
                _text_fallback(voice_manager, zere, config, logger, keep_running)
                if not keep_running[0]:
                    return
                continue

            print(f"Вы (голос): {voice_input}\n")

            if voice_input.strip().lower() in ("выход", "стоп"):
                keep_running[0] = False
                print("[Голос] Текстовый режим.\n")
                return

            _process_voice(voice_input, zere, config, logger, voice_manager)


def _process_voice(
    voice_input: str,
    zere: ZereEngine,
    config: ZereConfig,
    logger: LogService,
    voice_manager: VoiceManager,
) -> None:
    try:
        answer = zere.process(voice_input)

        logger.info(f"ZERE: {answer}")

        print(f"\nZERE: {answer}\n")

        if config.voice_enabled:
            voice_manager.speak(answer)
    except Exception as ex:  # noqa: BLE001
        logger.error(str(ex))
        print(f"\nОшибка: {ex}\n")


if __name__ == "__main__":
    sys.exit(main())
