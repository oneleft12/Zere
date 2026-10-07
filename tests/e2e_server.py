"""E2E-раннер: панель ZERE на фиксированном порту с фейковыми сервисами.

Запускается Playwright (panel/e2e/playwright.config.ts) через webServer:
детерминированные данные из tests/test_panel_api.py, без Ollama, микрофона
и внешней сети. Порт фиксирован (E2E_PORT, по умолчанию 8099), чтобы конфиг
Playwright знал URL заранее; конфигурация подменяется на временный каталог,
чтобы E2E не трогал реальный config/config.json.

Запуск вручную: `python3 tests/e2e_server.py` (Ctrl+C — остановка).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from zere import paths as paths_module
from zere.ai.ai_service import AiService
from zere.ai.ollama_url_resolver import OllamaUrlResolver
from zere.api.server import PanelServer
from zere.core.configuration.zere_config import ZereConfig
from zere.core.plugins.plugin_config import PluginConfig

from tests.fake_http import (
    FakeSession,
    chat_response,
    models_response,
    ollama_pull_response,
    ollama_tags_response,
)
from tests.test_panel_api import (
    TOKEN,
    FakeApplicationLauncher,
    FakeConversationRepository,
    FakeEngine,
    FakeMemory,
    FakeProcessService,
    FakeSafeActionManager,
    FakeUpdater,
    FakeVoiceManager,
)

PORT = int(os.environ.get("E2E_PORT", "8099"))


def _ai_service() -> AiService:
    """Сервис ИИ с фейковым HTTP: детерминированное состояние для E2E.

    Облачный ключ не сохранён, локальная Ollama «запущена» с моделью
    qwen3.5:2b — экран «Подключение ИИ» показывает «Подключено: локальная
    модель», а проверка ключа и загрузка модели отвечают как у реального
    провайдера (сеть в E2E не используется).
    """
    session = (
        FakeSession()
        .route("GET", "/api/tags", ollama_tags_response(["qwen3.5:2b"]))
        .route("GET", "/models", models_response(["gpt-4o-mini"]))
        .route("POST", "/chat/completions", chat_response("pong"))
        .route(
            "POST",
            "/api/pull",
            ollama_pull_response(
                [
                    '{"status":"pulling manifest"}',
                    '{"status":"downloading","total":100,"completed":60}',
                    '{"status":"success"}',
                ]
            ),
        )
    )
    return AiService(session=session)


def main() -> None:
    # Проба Ollama резолвит DNS-хосты (7–17 с без Docker) — для E2E
    # отключаем, как это делают контрактные тесты.
    OllamaUrlResolver.resolve = staticmethod(lambda: None)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        original_config_path = paths_module.config_path
        original_plugins_config_path = paths_module.plugins_config_path
        paths_module.config_path = lambda: tmp / "config.json"
        paths_module.plugins_config_path = lambda: tmp / "plugins.json"
        panel: PanelServer | None = None

        try:
            panel = PanelServer(
                engine=FakeEngine(),
                config=ZereConfig(),
                memory=FakeMemory(),
                conversation=FakeConversationRepository(),
                plugin_config=PluginConfig(),
                process_service=FakeProcessService(),
                safe_actions=FakeSafeActionManager(),
                app_launcher=FakeApplicationLauncher(),
                voice=FakeVoiceManager(),
                # Обновление из GitHub: в E2E — «есть 1 новый коммит»,
                # без git, сети и записи в рабочую копию.
                updater=FakeUpdater(update_available=True),
                # ИИ: локальная модель «доступна», ключ не сохранён —
                # экран «Подключение ИИ» детерминирован, сеть не нужна.
                ai=_ai_service(),
                token=TOKEN,
                port=PORT,
            )
            panel.start()
            print(f"[e2e] http://127.0.0.1:{panel.port} (токен: {TOKEN})", flush=True)

            while True:
                time.sleep(30)
        except KeyboardInterrupt:
            pass
        finally:
            if panel is not None:
                panel.stop()
            paths_module.config_path = original_config_path
            paths_module.plugins_config_path = original_plugins_config_path


if __name__ == "__main__":
    main()
