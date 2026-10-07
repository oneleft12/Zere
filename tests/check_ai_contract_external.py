"""Контрактные проверки ИИ против уже запущенной панели (C# или Python).

Запускается в CI-джобе C#-редакции и локально: поднимает панель (`ZERE.exe
--panel --port 8091` или `python main.py`) и проверяет `/api/ai*` по
docs/api/openapi.yaml.

Почему отдельный файл, а не весь tests/test_panel_api.py: в режиме
ZERE_PANEL_EXTERNAL панель настоящая, поэтому нельзя подсунуть фейкового
провайдера, а живые ключи, модель и историю пользователя трогать нельзя.
Здесь выполняются только безопасные проверки: форма ответов, валидация,
401/405 и отказы до обращения к провайдеру.

Режимы:

- по умолчанию — только безопасные проверки (форма ответов, валидация,
  401/405/400), ключи и модель пользователя не трогаются;
- `--full` — дополнительно проверяет полный цикл «ключ → проверка → чат»,
  сохраняя временный ключ в config/ai.json **с восстановлением файла после
  прогона**, и обращаясь к фейковому провайдеру
  (`tests/fake_openai_server.py`) вместо настоящего API.

Запуск:
    # 1. панель (Python: python main.py; C#: ZERE.exe --panel --port 8091)
    # 2. безопасные проверки
    python tests/check_ai_contract_external.py 8080
    # 3. полный цикл с фейковым провайдером
    python tests/fake_openai_server.py 8123 &
    python tests/check_ai_contract_external.py 8080 --full
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Порт: аргумент командной строки важнее переменной окружения — при запуске
# Windows-панели из WSL переменные окружения в Windows-процесс не попадают.
ARGUMENTS = [argument for argument in sys.argv[1:] if not argument.startswith("--")]
FULL_FLOW = "--full" in sys.argv

PORT = (
    ARGUMENTS[0]
    if ARGUMENTS and ARGUMENTS[0].isdigit()
    else os.environ.get("ZERE_PANEL_PORT", "8080")
)
WAIT_SECONDS = float(os.environ.get("ZERE_PANEL_WAIT", "120"))

# Фейковый провайдер (tests/fake_openai_server.py) и его ключи.
FAKE_PROVIDER_URL = os.environ.get("ZERE_FAKE_PROVIDER", "http://127.0.0.1:8123/v1")
GOOD_KEY = "sk-good-abcdefghijklmnop"


def wait_for_panel() -> None:
    """Ждёт config/panel.token и ответ /api/health — панель стартует не мгновенно."""
    os.environ["ZERE_PANEL_EXTERNAL"] = "1"
    os.environ["ZERE_PANEL_PORT"] = PORT

    from tests import test_panel_api as panel  # noqa: PLC0415 — путь уже в sys.path

    token_file = REPO_ROOT / "config" / "panel.token"
    deadline = time.monotonic() + WAIT_SECONDS

    while time.monotonic() < deadline:
        if token_file.exists():
            external = panel._ExternalPanel(int(PORT), token_file.read_text(encoding="utf-8").strip())

            try:
                status, _, _ = panel.call(external, "GET", "/api/health")

                if status == 200:
                    return
            except OSError:
                pass  # сервер ещё не принял сокет

        time.sleep(1)

    raise SystemExit(
        f"панель на порту {PORT} не ответила за {WAIT_SECONDS:.0f} с "
        "(проверьте, что она запущена и порт совпадает с ZERE_PANEL_PORT)"
    )


def check(label: str, condition: bool, detail: object = "") -> bool:
    if condition:
        print(f"OK   {label}")
        return True

    print(f"FAIL {label} {detail}")
    return False


def run_full_flow() -> list[str]:
    """Полный цикл на фейковом провайдере: ключ → проверка → облачный чат.

    config/ai.json сохраняется и восстанавливается: локальный прогон не
    меняет настройки пользователя надолго. В историю диалогов при этом
    попадает одна тестовая пара (в CI рабочая копия одноразовая).
    """
    import shutil  # noqa: PLC0415 — нужен только в режиме --full
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    from tests import test_panel_api as panel  # noqa: PLC0415

    # Фейковый провайдер в CI поднимается в фоне — ждём его готовности.
    probe = urllib.request.Request(
        f"{FAKE_PROVIDER_URL}/models", headers={"Authorization": f"Bearer {GOOD_KEY}"}
    )
    deadline = time.monotonic() + 30

    while True:
        try:
            with urllib.request.urlopen(probe, timeout=5) as response:
                if response.status == 200:
                    break
        except (urllib.error.URLError, OSError):
            pass

        if time.monotonic() > deadline:
            raise SystemExit(
                f"фейковый провайдер {FAKE_PROVIDER_URL} не отвечает — "
                "запустите tests/fake_openai_server.py 8123"
            )

        time.sleep(1)

    config_path = REPO_ROOT / "config" / "ai.json"
    backup = config_path.with_suffix(".json.check-backup")
    had_config = config_path.exists()
    failed: list[str] = []

    if had_config:
        shutil.copy2(config_path, backup)

    def record(label: str, condition: bool, detail: object = "") -> None:
        if not check(label, condition, detail):
            failed.append(label)

    try:
        with panel.running_panel() as (external, _):
            status, raw, _ = panel.call(external, "GET", "/api/ai")
            record("--full: панель отвечает", status == 200, status)

            status, raw, _ = panel.call(
                external,
                "POST",
                "/api/ai/key",
                body={
                    "apiKey": GOOD_KEY,
                    "cloudProvider": "custom",
                    "cloudBaseUrl": FAKE_PROVIDER_URL,
                    "cloudModel": "test-model",
                },
            )
            ai = json.loads(raw.decode("utf-8"))
            record("--full: рабочий ключ сохранён", status == 200 and ai.get("activeProvider") == "cloud",
                   (status, ai))
            record("--full: наружу только маска", ai.get("cloud", {}).get("keyMask") == "sk-...mnop",
                   ai.get("cloud"))
            record("--full: ключ не утёк в ответ", GOOD_KEY not in raw.decode("utf-8"))
            record("--full: сводка про облако",
                   "Подключено: облачная модель" in ai.get("summary", ""), ai.get("summary"))

            for key, expected_status, expected_code in (
                ("sk-bad-000000000000000", 400, "AI_KEY_INVALID"),
                ("sk-nocredit-000000000000", 400, "AI_NO_CREDITS"),
                ("sk-ratelimit-00000000000", 429, "AI_RATE_LIMIT"),
            ):
                status, raw, _ = panel.call(
                    external,
                    "POST",
                    "/api/ai/key/test",
                    body={"apiKey": key, "cloudBaseUrl": FAKE_PROVIDER_URL, "cloudModel": "test-model"},
                )
                error = json.loads(raw.decode("utf-8"))
                record(f"--full: {expected_code}", status == expected_status and error.get("code") == expected_code,
                       (status, error))

            # Чат должен ответить через облачного провайдера (AIHandler → прокси).
            status, raw, _ = panel.call(
                external, "GET", "/api/chat/stream?text=" + quote("привет")
            )
            record("--full: чат отвечает облаком", b"event: done" in raw and "ОТВЕТ ОБЛАКА" in raw.decode("utf-8"),
                   raw[:200])

            # Удаление ключа возвращает провайдера к локальной модели.
            status, raw, _ = panel.call(external, "DELETE", "/api/ai/key")
            ai = json.loads(raw.decode("utf-8"))
            record("--full: ключ удаляется", status == 200 and ai.get("cloud", {}).get("keySaved") is False,
                   (status, ai))
    finally:
        if had_config:
            shutil.copy2(backup, config_path)
            backup.unlink(missing_ok=True)
        elif config_path.exists():
            config_path.unlink()

        print("     (config/ai.json восстановлен)")

    return failed


def main() -> int:
    wait_for_panel()

    from tests import test_panel_api as panel  # noqa: PLC0415

    names = sorted(name for name in dir(panel) if name.startswith("test_ai_"))
    failed: list[str] = []

    for name in names:
        try:
            getattr(panel, name)()
        except Exception as ex:  # noqa: BLE001 — отчёт важнее типа исключения
            failed.append(name)
            print(f"FAIL {name}: {type(ex).__name__}: {ex}")
        else:
            print(f"OK  {name}")

    total = len(names)
    print(f"\nИТОГО: {total - len(failed)}/{total} контрактов /api/ai прошло")

    if FULL_FLOW:
        print(f"\nПолный цикл на фейковом провайдере {FAKE_PROVIDER_URL}:")
        failed.extend(run_full_flow())

    if failed:
        print("Провалено: " + ", ".join(failed))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
