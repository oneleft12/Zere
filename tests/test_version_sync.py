"""Версия проекта — из config/config.json, а не из пяти захардкоженных мест.

Исторически 1.8.0 жило в config.json, Zere.iss, ZereSetup.cs, install.ps1,
build-installer.ps1, build-setup.ps1 и ZereConfig. Тест фиксирует, что
запасные значения совпадают с единственным источником: иначе установщик и
приложение начинают врать о версии.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from zere.core.configuration.zere_config import ZereConfig

ROOT = Path(__file__).resolve().parents[1]


def _config_version() -> str:
    payload = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    return str(payload["version"])


def test_runtime_default_matches_config() -> None:
    assert ZereConfig().version == _config_version()


def test_inno_setup_defaults_match_config() -> None:
    source = (ROOT / "installer" / "Zere.iss").read_text(encoding="utf-8")
    version = _config_version()
    assert f'#define MyAppVersion "{version}"' in source
    assert f'#define FileVersion "{version}.0"' in source


def test_build_script_defaults_match_config() -> None:
    version = _config_version()

    for name in ("build-installer.ps1", "build-setup.ps1"):
        source = (ROOT / "installer" / name).read_text(encoding="utf-8")
        assert re.search(rf"\$version = '{re.escape(version)}'", source), name


def test_setup_assembly_version_matches_config() -> None:
    source = (ROOT / "installer" / "ZereSetup.cs").read_text(encoding="utf-8")
    version = _config_version()

    assert f'AssemblyVersion("{version}.0")' in source
    assert f'AssemblyFileVersion("{version}.0")' in source


def test_installer_template_version_matches_config() -> None:
    """Шаблон config.json в install.ps1 — запасной, но обязан совпадать."""
    source = (ROOT / "installer" / "install.ps1").read_text(encoding="utf-8")
    block = source[source.index("$DefaultConfigJson"):source.index("'@", source.index("$DefaultConfigJson"))]

    assert f'"version": "{_config_version()}"' in block
