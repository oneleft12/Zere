"""CLI обновления: `python -m zere.core.update [--check|--apply] [--no-deps]`.

Нужен для случая, когда панель не поднимается: проверку и обновление можно
сделать из консоли теми же средствами, что и кнопки панели.
"""

from __future__ import annotations

import sys

from zere.core.update.updater import UpdateBusyError, UpdateService


def _print_status(state: dict) -> None:
    current = state.get("current")
    target = state.get("target")

    print(f"Ветка:          {state['branch']} ({state['remote']})")
    print(f"Репозиторий:    {state.get('remoteUrl') or '—'}")
    print(f"Локальный HEAD: {current['short'] + ' ' + current['subject'] if current else '—'}")

    if state.get("error"):
        print(f"Ошибка:         {state['error']}")

    if state.get("updateAvailable"):
        print(f"Доступно:       {state['behind']} коммитов позади {state['remote']}")
        if target:
            print(f"Удалённый HEAD: {target['short']} {target['subject']}")
        for commit in state.get("commits", []):
            print(f"  • {commit['short']} {commit['subject']} ({commit['author']})")
    else:
        print("Доступно:       обновлений нет")

    if state.get("blockedReason"):
        print(f"Блокировка:     {state['blockedReason']}")

    print(f"Проверено:      {state.get('checkedAt') or '—'}")


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0

    service = UpdateService()

    try:
        if "--apply" in argv:
            outcome = service.apply(install_dependencies="--no-deps" not in argv)
            print(outcome["message"])
            _print_status(service.status())
            return 0 if outcome["ok"] else 1

        if "--check" in argv:
            _print_status(service.check())
            return 0

        _print_status(service.status())
        return 0
    except UpdateBusyError as ex:
        print(f"[Обновление] {ex}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
