"""Бенчмарк роутера Jev на размеченных фразах ZERE.

Отвечает на вопросы, от которых зависят пороги в config/router.json:
- как часто Jev угадывает интент на живых формулировках (синонимы, вопросы,
  запреты, попытки инъекций);
- какая доля фраз решается автоматически, какая уточняется, какая уходит в ИИ;
- сколько стоят решения и какова задержка (p50/p95);
- какие пороги дают лучший компромисс «авто-выполнено / ошибок».

Сырые решения сохраняются (`--save`), поэтому пороги можно пересчитывать
без новых запросов (`--from`): Jev не переспрашивают дважды.

Запуск:
    python3 tools/jev_bench.py --check
    python3 tools/jev_bench.py --save bench-latest.json
    python3 tools/jev_bench.py --from bench-latest.json

Нужен ключ OpenRouter (`sk-or-...`) — Jev вызывается по-настоящему:
`JEV_API_KEY`/`OPENROUTER_API_KEY` или `config/router.json`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from zere.core.routing.jev_client import JevClient, JevError
from zere.core.routing.jev_router import (
    ACTION_CLARIFY,
    ACTION_CONFIRM,
    ACTION_ERROR,
    ACTION_EXECUTE,
    ACTION_LLM,
    ACTION_OFF,
    JevIntentRouter,
    LocalCatalog,
    RouterSettings,
)

DEFAULT_PHRASES = REPO_ROOT / "tools" / "jev_bench_phrases.jsonl"

#: Действия, которые считаются «роутер справился сам».
AUTO_ACTIONS = (ACTION_EXECUTE, ACTION_CONFIRM)

#: Сетка порогов для подбора компромисса.
THRESHOLD_GRID = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.93, 0.95, 0.98)


def load_phrases(path: Path, limit: Optional[int] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as ex:
            raise SystemExit(f"{path}:{number}: битая строка JSONL: {ex}") from ex
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise SystemExit(f"{path}:{number}: нет поля text")
        rows.append(row)
    return rows[:limit] if limit else rows


def check_key(settings: RouterSettings) -> int:
    client = JevClient(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        timeout=settings.timeout,
    )
    try:
        result = client.check()
    except JevError as ex:
        print(f"ОШИБКА {ex.code}: {ex.message}", file=sys.stderr)
        return 1
    finally:
        client.close()

    print(result["message"])
    if result["probability"] is not None:
        print(f"проверочный вопрос: вероятность «да» = {result['probability']:.2f}")
    return 0


def run_bench(args: argparse.Namespace) -> int:
    settings = RouterSettings.load()
    settings.enabled = True
    if args.strategy:
        settings.strategy = args.strategy

    if not settings.api_key:
        print(settings.diagnosis(), file=sys.stderr)
        print(
            "Jev работает по ключу OpenRouter (`sk-or-...`). Ключ шлюза "
            "OpenCode Go (`oc_sk_...`) для Jev не подходит.",
            file=sys.stderr,
        )
        return 2

    if args.check:
        return check_key(settings)

    phrases = load_phrases(Path(args.phrases), args.limit)

    catalog = None if args.no_catalog else LocalCatalog()
    router = JevIntentRouter(settings, catalog=catalog, edition="python")

    results: list[dict[str, Any]] = []
    print(f"Фраз: {len(phrases)} · стратегия: {settings.strategy} · модель: {settings.model}\n")

    for index, row in enumerate(phrases, start=1):
        decision = router.route(row["text"])
        results.append(
            {
                "text": row["text"],
                "expectedIntent": row.get("intent"),
                "expectAction": row.get("expectAction"),
                "note": row.get("note"),
                **decision.to_public_dict(),
            }
        )
        mark = "OK " if _is_correct(results[-1]) else "МИМО"
        expected = row.get("intent") or "—"
        print(
            f"{index:>3}. {mark} «{row['text'][:52]}» → {decision.intent_id or decision.action} "
            f"({_fmt(decision.confidence)}), ждали {expected}"
        )

    router.close()
    report(results, settings)

    if args.save:
        Path(args.save).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nСырые решения сохранены: {args.save}")

    return 0


def report_from_file(path: str) -> int:
    results = json.loads(Path(path).read_text(encoding="utf-8"))
    report(results, RouterSettings.load())
    return 0


def _is_correct(result: dict[str, Any]) -> bool:
    """Верно ли решение: интент (если размечен) и действие (если задано)."""
    expect_action = result.get("expectAction")
    if expect_action == "llm" and result["action"] not in (ACTION_LLM, ACTION_CLARIFY):
        return False
    expected_intent = result.get("expectedIntent")
    if expected_intent:
        return result["intent"] == expected_intent
    return result["action"] in (ACTION_LLM, ACTION_CLARIFY, ACTION_EXECUTE, ACTION_CONFIRM)


def report(results: list[dict[str, Any]], settings: RouterSettings) -> None:
    if not results:
        print("Нечего считать: пустой набор.")
        return

    total = len(results)
    correct = sum(1 for row in results if _is_correct(row))
    errors = [row for row in results if row["action"] == ACTION_ERROR]

    actions: dict[str, int] = {}
    intents: dict[str, dict[str, int]] = {}
    dangerous: list[dict[str, Any]] = []

    for row in results:
        actions[row["action"]] = actions.get(row["action"], 0) + 1

        expected = row.get("expectedIntent")
        if not expected:
            continue

        bucket = intents.setdefault(expected, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if row["intent"] == expected:
            bucket["correct"] += 1
        if row["action"] in AUTO_ACTIONS and expected != row["intent"]:
            dangerous.append(row)

    latencies = [row["latencyMs"] for row in results if row.get("latencyMs")]
    costs = [row.get("cost") for row in results if row.get("cost") is not None]
    total_cost = sum(costs) if costs else 0.0

    print("\n── Итог ──────────────────────────────────────────────")
    print(f"Точность решений:        {correct}/{total} ({100 * correct / total:.1f}%)")
    print(f"Ошибки вызова Jev:       {len(errors)}")
    print(f"Авто-выполнено:          {actions.get(ACTION_EXECUTE, 0)}")
    print(f"Требует подтверждения:   {actions.get(ACTION_CONFIRM, 0)}")
    print(f"Уточнение у пользователя: {actions.get(ACTION_CLARIFY, 0)}")
    print(f"Ушло в ИИ:               {actions.get(ACTION_LLM, 0)}")
    print(f"Роутер выключен:         {actions.get(ACTION_OFF, 0)}")

    if latencies:
        print(
            f"Задержка:                p50 {statistics.median(latencies):.0f} мс, "
            f"p95 {_percentile(latencies, 95):.0f} мс, "
            f"макс {max(latencies)} мс"
        )
    if costs:
        print(
            f"Стоимость:               ${total_cost:.6f} за {total} фраз "
            f"(${1000 * total_cost / total:.4f} за 1000)"
        )

    if dangerous:
        print(f"\n⚠ Опасные случаи (выполнено не то): {len(dangerous)}")
        for row in dangerous:
            print(f"  «{row['text'][:60]}» → {row['intent']}, ждали {row['expectedIntent']}")

    print("\n── По интентам (там, где размечено) ──────────────────")
    for intent, bucket in sorted(
        intents.items(), key=lambda item: item[1]["correct"] / item[1]["total"]
    ):
        share = 100 * bucket["correct"] / bucket["total"]
        flag = "" if share == 100 else "  ←"
        print(f"{intent:<22} {bucket['correct']}/{bucket['total']} ({share:.0f}%){flag}")

    print("\n── Пороги (по сохранённым вероятностям) ──────────────")
    print("порог  авто  из них верно  ошибок  уточнено/в ИИ")
    for threshold in THRESHOLD_GRID:
        auto = [row for row in results if row["action"] in AUTO_ACTIONS]
        # Пересчёт «как если бы порог был другим»: команды с уверенностью
        # ниже порога не выполняются, а уточняются или уходят в ИИ.
        command_like = [row for row in results if row.get("expectedIntent") not in (None, "chat")]
        auto_rows = [row for row in command_like if (row.get("confidence") or 0) >= threshold]
        auto_correct = sum(1 for row in auto_rows if row["intent"] == row["expectedIntent"])
        fallback = len(command_like) - len(auto_rows)
        print(
            f"{threshold:<6.2f} {len(auto_rows):<5} {auto_correct:<15} "
            f"{len(auto_rows) - auto_correct:<7} {fallback}"
        )
    print(
        "\nКак читать: «авто» — сколько команд выполнилось бы при таком пороге, "
        "«ошибок» — сколько из них не тот интент. Порог из config/router.json "
        "ставьте по цене ошибки: для необратимых действий (питание, удаление, "
        "завершение процессов) — выше, чем critical_threshold."
    )
    print(f"Текущие пороги: execute {settings.execute_threshold}, "
          f"clarify {settings.clarify_threshold}, critical {settings.critical_threshold}")


def _percentile(values: list[int], percent: int) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(percent / 100 * len(ordered)) - 1))
    return float(ordered[index])


def _fmt(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.2f}"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 tools/jev_bench.py",
        description="Бенчмарк роутера интентов ZERE на Jev.",
    )
    parser.add_argument("--check", action="store_true", help="проверить ключ и адрес Jev")
    parser.add_argument("--phrases", default=str(DEFAULT_PHRASES), help="размеченные фразы (JSONL)")
    parser.add_argument("--limit", type=int, help="ограничить число фраз")
    parser.add_argument("--strategy", choices=("single", "domain"), help="стратегия роутера")
    parser.add_argument("--no-catalog", action="store_true", help="без списков приложений/процессов")
    parser.add_argument("--save", help="сохранить сырые решения в JSON")
    parser.add_argument("--from", dest="from_file", help="отчёт по сохранённым решениям (без сети)")
    args = parser.parse_args(argv)

    if args.from_file:
        return report_from_file(args.from_file)

    return run_bench(args)


if __name__ == "__main__":
    raise SystemExit(main())
