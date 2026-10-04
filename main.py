"""JARVIS — точка входа (Python-порт JARVIS.App/Program.cs)."""

from __future__ import annotations

import sys
import threading
import webbrowser

from jarvis import paths
from jarvis.ai.ollama_client import OllamaClient
from jarvis.api.server import PanelServer
from jarvis.core.configuration.jarvis_config import JarvisConfig
from jarvis.core.context.runtime_context import RuntimeContext
from jarvis.core.dependencies.dependency_checker import DependencyChecker
from jarvis.core.engine import JarvisEngine
from jarvis.core.logging.log_service import LogService
from jarvis.core.plugins.plugin_config import PluginConfig
from jarvis.core.plugins.plugin_manager import PluginManager
from jarvis.core.plugins.settings.settings_menu import SettingsMenu
from jarvis.core.services import create_services
from jarvis.memory.database.conversation_repository import ConversationRepository
from jarvis.memory.database.memory_database import MemoryDatabase
from jarvis.memory.database.memory_repository import MemoryRepository
from jarvis.tools.applications.application_launcher import ApplicationLauncher
from jarvis.tools.windows.process_service import ProcessService
from jarvis.tools.windows.safe_action_manager import SafeActionManager
from jarvis.voice.voice_manager import VoiceManager


def main() -> None:
    config = JarvisConfig.load()
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

    checker = DependencyChecker(config)
    checker.run_all()
    checker.print_report()

    if not checker.all_critical_passed():
        checker.offer_install()

    if not checker.all_critical_passed():
        print("Критические зависимости не выполнены.")
        print("Устраните ошибки выше и запустите снова.")
        print("Нажмите Enter для выхода...")
        try:
            input()
        except EOFError:
            pass
        return

    print("Все зависимости в порядке.\n")

    # Предложить установку голосовых компонентов (не критичные)
    if config.voice_enabled:
        checker.offer_voice_install()

    services = create_services(config)

    services.get(MemoryDatabase)

    jarvis = services.get(JarvisEngine)
    voice_manager = VoiceManager()

    # Локальная панель (этап 1 GUI-плана): loopback + токен, контракт
    # docs/api/openapi.yaml. Сбой порта не должен ронять консоль.
    panel = PanelServer(
        engine=jarvis,
        config=services.get(JarvisConfig),
        memory=services.get(MemoryRepository),
        conversation=services.get(ConversationRepository),
        plugin_config=services.get(PluginConfig),
        process_service=services.get(ProcessService),
        safe_actions=services.get(SafeActionManager),
        app_launcher=services.get(ApplicationLauncher),
        voice=voice_manager,
    )
    # Авто-открытие панели при старте (этапы 5–6): окно приложения,
    # фолбэк — браузер; panel_url остаётся None, если сервер не поднялся.
    panel_url: str | None = None

    try:
        panel.start()
        panel_url = f"http://127.0.0.1:{panel.port}"
        print(f"[Панель] {panel_url} (токен: config/panel.token)")
        _open_panel_window(panel_url, logger)
    except OSError as ex:
        logger.error(f"PanelServer: {ex}")
        print("[Панель] Не удалось запустить локальный сервер (порт занят?).")

    # Громкость голоса из config.json (voiceVolume, дефолт 0.5)
    voice_manager.config.volume = float(config.voice_volume)

    active_personality = jarvis.plugin_manager.active_personality
    if active_personality is not None:
        print(f"[Личность] {active_personality.name} | Стиль: {active_personality.style}\n")

    if config.voice_enabled:
        voice_manager.initialize(str(active_personality.style) if active_personality else None)
        print("[Голос] Режим: текст + голос")

        # Предзагрузка Whisper в фоне (ROADMAP 1.3): не блокируем старт
        threading.Thread(
            target=voice_manager.preload_whisper,
            daemon=True,
        ).start()
    else:
        print("[Голос] Отключен. Только текстовый режим.")

    # Прогрев Ollama в фоне (этап 1, анализ S5): первый «настоящий»
    # запрос не платит за загрузку модели; keep_alive из конфига
    # удерживает её в памяти. Ошибки не критичны.
    def _warmup_llm() -> None:
        try:
            client = services.get(OllamaClient)
            if client is not None:
                client.warmup()
        except Exception as ex:  # noqa: BLE001 — прогрев не должен мешать старту
            logger.error(f"Warmup: {ex}")

    threading.Thread(target=_warmup_llm, daemon=True).start()

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

            run_voice_mode(voice_manager, jarvis, config, logger, voice_mode_holder := [True])

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

            active_personality = jarvis.plugin_manager.active_personality
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
            answer = jarvis.process(message)

            logger.info(f"JARVIS: {answer}")

            print()
            print(f"JARVIS: {answer}")
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
    logger.info("JARVIS завершил работу.")


def _open_panel_in_browser(url: str, logger: LogService) -> None:
    """Открывает панель в браузере (этап 5): сбой браузера не роняет консоль."""
    try:
        webbrowser.open(url)
        print(f"[Панель] Открыта в браузере: {url}")
    except Exception as ex:  # noqa: BLE001 — браузер может быть недоступен вовсе
        logger.error(f"PanelBrowser: {ex}")
        print(f"[Панель] Браузер не открылся — вручную: {url}")


_panel_window_lock = threading.Lock()
_panel_window_ref: dict = {"window": None}


def _open_panel_window(url: str, logger: LogService) -> None:
    """Открывает панель отдельным окном приложения (этап 6), а не вкладкой.

    Windows: pywebview (WebView2), если пакет установлен; иначе — фолбэк
    в браузер. Любая сбой окна не должна ронять консоль.
    """
    with _panel_window_lock:
        window = _panel_window_ref["window"]
        if window is not None:
            try:
                window.restore()
                window.show()
                return
            except Exception:  # noqa: BLE001 — окно закрыто, создаём новое
                _panel_window_ref["window"] = None

        try:
            import webview  # pywebview — необязательная зависимость
        except ImportError:
            _open_panel_in_browser(url, logger)
            return

        try:
            new_window = webview.create_window("JARVIS", url, width=1280, height=840)
            _panel_window_ref["window"] = new_window
            threading.Thread(
                target=_run_panel_window, args=(webview, url, logger), daemon=True
            ).start()
            print(f"[Панель] Открыта в окне приложения: {url}")
        except Exception as ex:  # noqa: BLE001
            logger.error(f"PanelWindow: {ex}")
            _open_panel_in_browser(url, logger)


def _run_panel_window(webview, url: str, logger: LogService) -> None:
    """Цикл окна pywebview в фоновом потоке; сбой — фолбэк в браузер."""
    try:
        webview.start()
    except Exception as ex:  # noqa: BLE001
        logger.error(f"PanelWindow: {ex}")
        _open_panel_in_browser(url, logger)


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


def _text_fallback(voice_manager: VoiceManager, jarvis: JarvisEngine, config: JarvisConfig, logger: LogService, keep_running: list[bool]) -> None:
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

    _process_voice(text_input, jarvis, config, logger, voice_manager)


def run_voice_mode(
    voice_manager: VoiceManager,
    jarvis: JarvisEngine,
    config: JarvisConfig,
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

            print("\n💤 Спящий режим. Скажите 'Джарвис' для активации.")
            print("   Или напишите 'выход' для отключения голосового режима.\n")

            cancel_event = threading.Event()

            wake_detected = False
            wake_result: list[bool] = [False]
            wake_error: list[BaseException] = []

            def wake_worker() -> None:
                try:
                    wake_result[0] = voice_manager.wait_for_wake_word(cancel_event)
                except BaseException as exc:  # noqa: BLE001
                    wake_error.append(exc)

            wake_thread = threading.Thread(target=wake_worker, daemon=True)
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
                _text_fallback(voice_manager, jarvis, config, logger, keep_running)
                if not keep_running[0]:
                    return
                print("💤 Возвращаюсь в спящий режим.\n")
                continue

            print(f"Вы (голос): {voice_input}\n")

            if voice_input.strip().lower() in ("выход", "стоп"):
                keep_running[0] = False
                print("[Голос] Текстовый режим.\n")
                return

            _process_voice(voice_input, jarvis, config, logger, voice_manager)
            print("💤 Возвращаюсь в спящий режим.\n")
        else:
            # Обычный режим без ключевого слова (старый вариант)
            print("[ГОЛОС] Скажите команду... ")
            voice_input = voice_manager.listen()

            if not voice_input or not voice_input.strip():
                print("Не удалось распознать речь.")
                _text_fallback(voice_manager, jarvis, config, logger, keep_running)
                if not keep_running[0]:
                    return
                continue

            print(f"Вы (голос): {voice_input}\n")

            if voice_input.strip().lower() in ("выход", "стоп"):
                keep_running[0] = False
                print("[Голос] Текстовый режим.\n")
                return

            _process_voice(voice_input, jarvis, config, logger, voice_manager)


def _process_voice(
    voice_input: str,
    jarvis: JarvisEngine,
    config: JarvisConfig,
    logger: LogService,
    voice_manager: VoiceManager,
) -> None:
    try:
        answer = jarvis.process(voice_input)

        logger.info(f"JARVIS: {answer}")

        print(f"\nJARVIS: {answer}\n")

        if config.voice_enabled:
            voice_manager.speak(answer)
    except Exception as ex:  # noqa: BLE001
        logger.error(str(ex))
        print(f"\nОшибка: {ex}\n")


if __name__ == "__main__":
    sys.exit(main())
