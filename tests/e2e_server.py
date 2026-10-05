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
from zere.ai.ollama_url_resolver import OllamaUrlResolver
from zere.api.server import PanelServer
from zere.core.configuration.zere_config import ZereConfig
from zere.core.plugins.plugin_config import PluginConfig

from tests.test_panel_api import (
    TOKEN,
    FakeApplicationLauncher,
    FakeConversationRepository,
    FakeEngine,
    FakeMemory,
    FakeProcessService,
    FakeSafeActionManager,
    FakeVoiceManager,
)

PORT = int(os.environ.get("E2E_PORT", "8099"))


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
