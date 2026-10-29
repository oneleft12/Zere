"""Обновление установленной сборки без .git: GitHub API + zipball ветки.

Setup.exe ставит git archive — `.git` в каталоге нет, и прежний updater
отказывал («Обновление через git недоступно»). Второй канал: метка коммита
в config/build-info.json сравнивается с HEAD ветки через GitHub API, обновление
накладывается zipball'ом. Сеть подменяется — тесты без интернета.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from zere.core.update.updater import (
    DEPENDENCIES_NOT_NEEDED,
    DEPENDENCIES_UPDATED,
    UpdateService,
)

OLD = "a" * 40
NEW = "b" * 40


def _zip(files: dict[str, str], top: str = "Jarvis-новый") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"{top}/{name}" if top else name, content)
    return buffer.getvalue()


def make_service(tmp_path: Path, *, commit: str = OLD, with_build_info: bool = True) -> UpdateService:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(
        json.dumps({"version": "1.8.0", "language": "ru"}), encoding="utf-8"
    )
    if with_build_info:
        (tmp_path / "config" / "build-info.json").write_text(
            json.dumps(
                {
                    "repository": "oneleft12/Jarvis",
                    "branch": "python-port",
                    "commit": commit,
                    "version": "1.8.0",
                    "builtAt": "2026-10-01T10:00:00+05:00",
                }
            ),
            encoding="utf-8",
        )

    (tmp_path / "main.py").write_text("old\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    return UpdateService(root=tmp_path)


def remote_commit(sha: str = NEW, message: str = "Новый коммит\n\nдетали") -> bytes:
    return json.dumps(
        {
            "sha": sha,
            "commit": {
                "message": message,
                "author": {"name": "Dan"},
                "committer": {"date": "2026-10-29T12:00:00Z"},
            },
        }
    ).encode("utf-8")


def test_status_without_build_info_is_honest(tmp_path: Path) -> None:
    service = make_service(tmp_path, with_build_info=False)
    service._http_get = lambda url, *, limit: remote_commit()  # type: ignore[method-assign]

    state = service.check()

    assert state["available"] is False
    assert "метки версии" in state["error"]
    assert state["canUpdate"] is False


def test_check_detects_new_commit(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._http_get = lambda url, *, limit: remote_commit()  # type: ignore[method-assign]

    state = service.check()

    assert state["available"] is True
    assert state["updateAvailable"] is True
    assert state["behind"] == 1
    assert state["canUpdate"] is True
    assert state["current"]["hash"] == OLD
    assert state["target"]["hash"] == NEW
    assert state["commits"][0]["subject"] == "Новый коммит"
    assert state["branch"] == "python-port"
    assert state["remote"] == "github"


def test_check_with_same_commit_has_no_update(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._http_get = lambda url, *, limit: remote_commit(OLD)  # type: ignore[method-assign]

    state = service.check()

    assert state["updateAvailable"] is False
    assert state["behind"] == 0
    assert state["commits"] == []


def test_network_error_is_reported_without_crash(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    def boom(url: str, *, limit: int) -> bytes:
        raise OSError("нет сети")

    service._http_get = boom  # type: ignore[method-assign]

    state = service.check()

    assert "Нет связи с GitHub" in state["error"]
    assert state["blockedReason"] == "нет связи с GitHub"
    assert state["canUpdate"] is False


def test_apply_copies_code_and_keeps_user_data(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    archive = _zip(
        {
            "main.py": "new\n",
            "requirements.txt": "requests\nnewpkg\n",
            "zere/new_module.py": "X = 1\n",
            "config/config.json": json.dumps({"version": "1.9.0", "language": "en"}),
            "config/build-info.json": "{}",
            "zere.db": "данные",
        }
    )

    def fake_get(url: str, *, limit: int) -> bytes:
        if "codeload" in url:
            return archive
        return remote_commit()

    service._http_get = fake_get  # type: ignore[method-assign]
    service._install_dependencies = lambda: DEPENDENCIES_UPDATED  # type: ignore[method-assign]

    outcome = service.apply()

    assert outcome["ok"] is True
    assert outcome["pulled"] == 1
    assert outcome["restartRequired"] is True
    assert outcome["dependencies"] == DEPENDENCIES_UPDATED
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "new\n"
    assert (tmp_path / "zere" / "new_module.py").is_file()

    # Данные пользователя не перезаписаны, но версия обновлена.
    config = json.loads((tmp_path / "config" / "config.json").read_text(encoding="utf-8"))
    assert config["language"] == "ru"
    assert config["version"] == "1.9.0"
    assert not (tmp_path / "zere.db").exists()

    build = json.loads((tmp_path / "config" / "build-info.json").read_text(encoding="utf-8"))
    assert build["commit"] == NEW
    assert build["version"] == "1.9.0"

    # После обновления проверка без сети видит уже новый коммит.
    assert service.status()["current"]["hash"] == NEW


def test_apply_without_changes_installs_no_dependencies(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    archive = _zip({"main.py": "new\n"})

    def fake_get(url: str, *, limit: int) -> bytes:
        return archive if "codeload" in url else remote_commit()

    service._http_get = fake_get  # type: ignore[method-assign]
    called: list[bool] = []
    service._install_dependencies = lambda: called.append(True) or DEPENDENCIES_UPDATED  # type: ignore[method-assign]

    outcome = service.apply()

    assert outcome["ok"] is True
    assert outcome["dependencies"] == DEPENDENCIES_NOT_NEEDED
    assert called == []


def test_apply_without_update_is_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service._http_get = lambda url, *, limit: remote_commit(OLD)  # type: ignore[method-assign]

    outcome = service.apply()

    assert outcome["ok"] is False
    assert "Обновлений нет" in outcome["message"]


def test_apply_rejects_zip_traversal(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    archive = _zip({"../evil.txt": "зло"}, top="")

    def fake_get(url: str, *, limit: int) -> bytes:
        return archive if "codeload" in url else remote_commit()

    service._http_get = fake_get  # type: ignore[method-assign]

    outcome = service.apply()

    assert outcome["ok"] is False
    assert "недопустимый путь" in outcome["message"]
    assert not (tmp_path.parent / "evil.txt").exists()


def test_apply_reports_download_failure(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    def fake_get(url: str, *, limit: int) -> bytes:
        if "codeload" in url:
            raise OSError("обрыв")
        return remote_commit()

    service._http_get = fake_get  # type: ignore[method-assign]

    outcome = service.apply()

    assert outcome["ok"] is False
    assert "Не удалось применить обновление" in outcome["message"]
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "old\n"


def test_parallel_operations_are_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    assert service._op_lock.acquire(blocking=False)

    try:
        with pytest.raises(Exception):
            service.check()
    finally:
        service._op_lock.release()
