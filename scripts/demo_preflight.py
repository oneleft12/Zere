#!/usr/bin/env python3
"""Предполётная проверка перед записью демо-видео ZERE (docs/DEMO_1MIN.md).

Скрипт отвечает на один вопрос: **готово ли то, что попадёт в кадр.**

Проверяет панель, локальную модель, непустые память и историю, состояние голоса,
индекс приложений, свежие ошибки в логах и наличие сборки панели. Умеет
подготовить демо-состояние: засеять память фактами и убрать ошибки из кадра.

Запуск (Windows, из корня репозитория):

    python scripts/demo_preflight.py                  # только проверка
    python scripts/demo_preflight.py --seed           # + демо-факты в память
    python scripts/demo_preflight.py --clean-logs     # + убрать errors.log из кадра
    python scripts/demo_preflight.py --seed --clean-logs

Код возврата: 0 — блокирующих проблем нет, 1 — есть FAIL (в кадр лучше не писать).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Демо-факты: ровно то, что произносится в сцене «Память» раскадровки.
DEMO_MEMORIES = (
    {"key": "имя", "value": "Dan", "category": "User"},
    {"key": "проект", "value": "ZERE", "category": "User"},
    {"key": "город", "value": "Москва", "category": "User"},
)

# Файлы и каталоги, которых не должно быть в кадре (см. §2 раскадровки).
NOT_ON_CAMERA = (
    "docs/PROJECT_AUDIT_REPORT.md",
    "docs/COMMERCIAL_RELEASE_PLAN.md",
    "docs/PROJECT_ANALYSIS_REPORT.md",
    "backups",
)


class Report:
    """Копилка результатов с человекочитаемым выводом."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, status: str, title: str, detail: str = "", fix: str = "") -> None:
        self.rows.append((status, title, detail, fix))

    def ok(self, title: str, detail: str = "") -> None:
        self.add("OK", title, detail)

    def warn(self, title: str, detail: str = "", fix: str = "") -> None:
        self.add("WARN", title, detail, fix)

    def fail(self, title: str, detail: str = "", fix: str = "") -> None:
        self.add("FAIL", title, detail, fix)

    @property
    def failed(self) -> bool:
        return any(status == "FAIL" for status, *_ in self.rows)

    def print(self) -> None:
        marks = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
        print()
        for status, title, detail, fix in self.rows:
            line = f"{marks[status]} {title}"
            if detail:
                line += f" — {detail}"
            print(line)
            if fix:
                print(f"       -> {fix}")

        counts = {key: sum(1 for row in self.rows if row[0] == key) for key in marks}
        print()
        print(f"Итого: {counts['OK']} ok, {counts['WARN']} warn, {counts['FAIL']} fail")
        if counts["FAIL"]:
            print("Есть блокирующие пункты: в кадр лучше не писать, пока не закрыты.")
        elif counts["WARN"]:
            print("Блокеров нет, но то, что помечено WARN, в кадр лучше не ставить.")
        else:
            print("Всё готово к записи.")


# ── HTTP к панели ────────────────────────────────────────────────────────────


def load_token(override: str | None = None) -> str | None:
    if override:
        return override.strip() or None
    path = ROOT / "config" / "panel.token"
    if not path.is_file():
        return None
    token = path.read_text(encoding="utf-8", errors="replace").strip()
    return token or None


def api(
    base_url: str,
    token: str,
    path: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: float = 10.0,
) -> tuple[object | None, str]:
    """Запрос к панели. Возвращает (данные, текст ошибки)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    request.add_header("X-ZERE-Token", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as ex:
        body = ex.read().decode("utf-8", errors="replace")
        try:
            error = json.loads(body).get("message") or ex.reason
        except (json.JSONDecodeError, AttributeError):
            error = ex.reason
        return None, f"HTTP {ex.code}: {error}"
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        return None, f"нет ответа: {ex}"

    if not body.strip():
        return None, ""
    try:
        return json.loads(body), ""
    except json.JSONDecodeError:
        return None, "ответ не является JSON"


def count_items(node: object) -> int | None:
    """Достаёт количество записей из ответа API (`items`/`total`/список)."""
    if isinstance(node, dict):
        for key in ("total",):
            if isinstance(node.get(key), int):
                return node[key]
        for key in ("items", "memories", "entries"):
            if isinstance(node.get(key), list):
                return len(node[key])
    if isinstance(node, list):
        return len(node)
    return None


# ── Проверки ─────────────────────────────────────────────────────────────────


def check_panel(report: Report, base_url: str, token: str | None) -> dict | None:
    if token is None:
        report.fail(
            "Токен панели",
            "нет config/panel.token",
            "запустите ZERE — токен создаётся автоматически",
        )
        return None
    report.ok("Токен панели", "config/panel.token прочитан")

    health, error = api(base_url, token, "/api/health", timeout=5.0)
    if health is None:
        report.fail(
            "Панель",
            f"{base_url} не отвечает ({error})",
            "запустите ZERE: .venv\\Scripts\\python.exe main.py",
        )
        return None

    version = health.get("version", "?")
    branch = health.get("branch", "?")
    report.ok("Панель", f"{base_url}, версия {version}, ветка {branch}")
    return health if isinstance(health, dict) else None


def check_ollama(report: Report, health: dict) -> None:
    state = str(health.get("ollama", "?"))
    if state == "ok":
        report.ok("Локальная модель", "Ollama отвечает")
    else:
        report.fail(
            "Локальная модель",
            f"ollama: {state}",
            "запустите `ollama serve` и прогрейте модель одним запросом в чат",
        )

    tts = health.get("tts") or {}
    engine = tts.get("engine", "?") if isinstance(tts, dict) else "?"
    whisper = health.get("whisper", "?")
    report.ok("Движки", f"TTS: {engine}, Whisper-модель: {whisper}")


def check_memory(report: Report, base_url: str, token: str, health: dict) -> None:
    count = None
    memory = health.get("memory")
    if isinstance(memory, dict) and isinstance(memory.get("count"), int):
        count = memory["count"]

    if count is None:
        node, error = api(base_url, token, "/api/memory")
        count = count_items(node) if node is not None else None
        if count is None and error:
            report.warn("Память", f"не удалось прочитать ({error})")
            return

    if count is None:
        report.warn("Память", "панель не отдала количество")
    elif count == 0:
        report.fail(
            "Память пуста",
            "на экране «Память» будет пустое состояние",
            "запустите: python scripts/demo_preflight.py --seed",
        )
    elif count < 3:
        report.warn(
            "Память почти пуста",
            f"записей: {count}",
            "для кадра нужно 3+ факта: python scripts/demo_preflight.py --seed",
        )
    else:
        report.ok("Память", f"записей: {count}")


def check_history(report: Report, base_url: str, token: str) -> None:
    node, error = api(base_url, token, "/api/history?limit=1")
    if node is None:
        report.warn("История", f"не удалось прочитать ({error})")
        return

    total = count_items(node) if isinstance(node, dict) and "total" in node else None
    if total is None:
        total = count_items(node)
    if total is None:
        report.warn("История", "панель не отдала количество")
    elif total == 0:
        report.fail(
            "История пуста",
            "на экране «История» будет пустое состояние",
            "наговорите 3–4 реплики в чате перед записью",
        )
    else:
        report.ok("История", f"записей: {total}")


def check_ai(report: Report, base_url: str, token: str) -> None:
    node, error = api(base_url, token, "/api/ai")
    if not isinstance(node, dict):
        report.warn("Подключение ИИ", f"не удалось прочитать ({error})")
        return

    active = node.get("activeProvider")
    mode = node.get("mode", "?")
    ready = node.get("ready")
    summary = node.get("summary", "")

    if not ready:
        report.fail(
            "ИИ не готов",
            str(summary or "провайдер не выбран"),
            "настройте локальную модель (Ollama) в панели → «Подключение ИИ»",
        )
    elif active == "cloud":
        report.warn(
            "Запросы идут в облако",
            f"режим: {mode}, {summary}",
            "для фразы «запросы не уходят в облако» переключите режим на локальный",
        )
    else:
        report.ok("Провайдер ИИ", f"режим: {mode}, активно: {active}, {summary}")


def check_voice(report: Report, base_url: str, token: str) -> None:
    node, error = api(base_url, token, "/api/voice")
    if not isinstance(node, dict):
        report.warn("Голос", f"не удалось прочитать ({error})")
        return

    caps = node.get("capabilities") or {}
    stt = bool(caps.get("sttTest"))
    pocket = bool(caps.get("pocketCloning"))
    reference = bool(caps.get("recordReference"))

    if stt:
        report.ok("Голос: микрофон", "capabilities.sttTest = true")
    else:
        report.warn(
            "Голос: микрофон недоступен",
            "capabilities.sttTest = false",
            "модуль голоса не включать; экран «Голос» в кадр не ставить",
        )

    if not pocket or not reference:
        hidden = ", ".join(
            name
            for name, flag in (("PocketTTS", pocket), ("запись референса", reference))
            if not flag
        )
        report.warn(
            "Экран «Голос» показывает бейджи",
            f"нет: {hidden}",
            "сцену голоса вести из «Чата», экран «Голос» в кадр не ставить",
        )


def check_apps(report: Report, base_url: str, token: str) -> None:
    node, error = api(base_url, token, "/api/apps")
    if node is None:
        report.warn("Индекс приложений", f"не удалось прочитать ({error})")
        return

    total = count_items(node)
    if total is None:
        report.warn("Индекс приложений", "панель не отдала количество")
    elif total == 0:
        report.warn(
            "Индекс приложений пуст",
            "экран «Приложения» будет пустым",
            "нажмите «Переиндексировать» или не показывайте экран",
        )
    else:
        report.ok("Индекс приложений", f"записей: {total}")


def check_plugins(report: Report, base_url: str, token: str) -> None:
    node, error = api(base_url, token, "/api/plugins")
    if not isinstance(node, dict):
        return
    if node.get("handlersConnected") is False:
        report.warn(
            "Экран «Плагины» в кадр не ставить",
            "сервер отдаёт handlersConnected = false, экран пишет «обработчики подключены: нет»",
            "не открывать /plugins и не заявлять расширение пайплайна плагинами",
        )


def check_files(report: Report) -> None:
    dist = ROOT / "panel" / "dist" / "index.html"
    if dist.is_file():
        report.ok("Сборка панели", "panel/dist/index.html на месте")
    else:
        report.fail(
            "Сборка панели отсутствует",
            "panel/dist/index.html не найден",
            "панель не отрисуется: пересоберите panel/ или возьмите релизную сборку",
        )

    errors_log = ROOT / "logs" / "errors.log"
    if not errors_log.is_file():
        report.ok("Логи", "logs/errors.log отсутствует — в кадре нечего показывать")
        return

    try:
        lines = errors_log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as ex:
        report.warn("Логи", f"не удалось прочитать errors.log ({ex})")
        return

    fresh = [line for line in lines[-40:] if "[ERROR]" in line]
    if fresh:
        report.warn(
            "В errors.log свежие ошибки",
            f"строк: {len(lines)}, из последних 40 — {len(fresh)} с [ERROR]",
            "экран «Логи» не показывать; при желании: --clean-logs",
        )
    else:
        report.ok("Логи", f"строк: {len(lines)}, свежих [ERROR] нет")


def check_camera_hygiene(report: Report) -> None:
    present = [name for name in NOT_ON_CAMERA if (ROOT / name).exists()]
    if present:
        report.warn(
            "Не открывать в кадре",
            ", ".join(present),
            "внутренние отчёты об аудите и backups/ на экране выдают незакрытые места",
        )
    else:
        report.ok("Кадр чист", "внутренних отчётов в дереве нет")


def check_db_direct(report: Report) -> None:
    """Запасная проверка по файлу БД — работает, даже если панель не поднята."""
    db = ROOT / "zere.db"
    if not db.is_file():
        report.warn("Файл zere.db", "не найден в корне репозитория")
        return
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
            memories = connection.execute("SELECT COUNT(*) FROM Memories").fetchone()[0]
            conversations = connection.execute(
                "SELECT COUNT(*) FROM Conversations"
            ).fetchone()[0]
    except sqlite3.Error as ex:
        report.warn("Файл zere.db", f"не удалось прочитать ({ex})")
        return
    report.ok("zere.db", f"Memories: {memories}, Conversations: {conversations}")


# ── Подготовка демо-состояния ────────────────────────────────────────────────


def seed_memory(report: Report, base_url: str, token: str) -> None:
    print("\nСею демо-факты в память…")
    for item in DEMO_MEMORIES:
        node, error = api(base_url, token, "/api/memory", method="POST", payload=item)
        if node is None:
            report.fail(
                "Не удалось записать факт",
                f"{item['key']} = {item['value']} ({error})",
                "панель запущена? повторите после старта ZERE",
            )
            return
        print(f"  записано: {item['key']} = {item['value']}")

    node, _ = api(base_url, token, "/api/memory")
    total = count_items(node)
    report.ok("Память засеяна", f"записей: {total if total is not None else '?'}")


def clean_logs(report: Report) -> None:
    errors_log = ROOT / "logs" / "errors.log"
    if not errors_log.is_file():
        report.ok("Логи чистить нечего", "logs/errors.log отсутствует")
        return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = errors_log.with_name(f"errors.demo-backup-{stamp}.log")
    try:
        shutil.move(str(errors_log), str(target))
    except OSError as ex:
        report.fail("Не удалось убрать errors.log", str(ex))
        return
    report.ok("Логи убраны из кадра", f"errors.log -> {target.name}")


# ── Точка входа ──────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Предполётная проверка перед записью демо ZERE (docs/DEMO_1MIN.md).",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8080",
        help="адрес панели (по умолчанию http://127.0.0.1:8080)",
    )
    parser.add_argument("--seed", action="store_true", help="записать демо-факты в память")
    parser.add_argument(
        "--clean-logs", action="store_true", help="убрать logs/errors.log из кадра"
    )
    parser.add_argument(
        "--token",
        default=None,
        help="токен панели (по умолчанию — из config/panel.token)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    args = parse_args(argv)
    base_url = args.url.rstrip("/")
    report = Report()

    print("ZERE — предполётная проверка демо")
    print(f"Корень: {ROOT}")
    print(f"Панель: {base_url}")

    token = load_token(args.token)
    health = check_panel(report, base_url, token)
    live = health is not None and token is not None

    # Подготовка — до проверок: иначе «Память пуста» и «свежие ошибки» сообщат
    # о состоянии, которое мы прямо сейчас и исправляем.
    if args.seed:
        if live:
            seed_memory(report, base_url, token)
        else:
            report.fail(
                "Засев памяти невозможен",
                "панель не поднята",
                "запустите ZERE, затем повторите с --seed",
            )

    if args.clean_logs:
        clean_logs(report)

    if live:
        check_ollama(report, health)
        check_memory(report, base_url, token, health)
        check_history(report, base_url, token)
        check_ai(report, base_url, token)
        check_voice(report, base_url, token)
        check_apps(report, base_url, token)
        check_plugins(report, base_url, token)
    else:
        check_db_direct(report)

    check_files(report)
    check_camera_hygiene(report)

    report.print()
    print()
    print("Напоминание: в кадр не должны попасть консоль ZERE, экраны «Плагины» и")
    print("«Логи», внутренние отчёты об аудите и вторая редакция проекта.")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
