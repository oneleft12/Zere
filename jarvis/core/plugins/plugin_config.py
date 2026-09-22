"""Порт JARVIS.Core/Plugins/PluginConfig.cs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict

from jarvis import paths


@dataclass
class PluginConfig:
    ActivePersonalityId: str = "personality"
    ActivePersonalityStyle: str = "Friendly"
    ActiveCommandHandlerId: str = ""
    PluginSettings: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def config_path(cls) -> Path:
        return paths.plugins_config_path()

    @classmethod
    def load(cls) -> "PluginConfig":
        config_path = paths.plugins_config_path()

        config_dir = config_path.parent
        if config_dir is not None:
            config_dir.mkdir(parents=True, exist_ok=True)

        if not config_path.exists():
            config = cls()
            cls.save(config)
            return config

        text = config_path.read_text(encoding="utf-8")

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return cls()

        if not isinstance(data, dict):
            return cls()

        # PropertyNameCaseInsensitive — как в System.Text.Json
        known = {f.name: f for f in fields(cls)}
        lower_map = {name.lower(): name for name in known}

        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            resolved = known.get(key) or known.get(lower_map.get(key.lower(), ""))
            if resolved is None:
                continue
            if resolved.name == "PluginSettings" and not isinstance(value, dict):
                continue
            kwargs[resolved.name] = value

        try:
            return cls(**kwargs)
        except TypeError:
            return cls()

    @classmethod
    def save(cls, config: "PluginConfig") -> None:
        config_path = paths.plugins_config_path()
        json_text = json.dumps(asdict(config), indent=2, ensure_ascii=False)
        config_path.write_text(json_text, encoding="utf-8")

    def get_setting(self, plugin_id: str, key: str, default_value: str = "") -> str:
        full_key = f"{plugin_id}.{key}"
        return self.PluginSettings.get(full_key, default_value)

    def set_setting(self, plugin_id: str, key: str, value: str) -> None:
        full_key = f"{plugin_id}.{key}"
        self.PluginSettings[full_key] = value
