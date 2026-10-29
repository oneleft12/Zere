"""Тесты мини-DI и сборки сервисов, включая аварийный путь роутера Jev.

Регрессия: `_create_jev_handler` вызывал `log_error`, который не был
импортирован, — при сбое сборки роутера приложение падало с NameError
вместо честного отката на обычный конвейер.
"""

from __future__ import annotations

from typing import Any

import pytest

from zere import paths
from zere.core import services
from zere.core.configuration.zere_config import ZereConfig
from zere.core.plugins.plugin_config import PluginConfig
from zere.core.services import ServiceContainer, create_services


class Value:
    def __init__(self, value: str) -> None:
        self.value = value


def test_singleton_is_returned_as_is() -> None:
    container = ServiceContainer()
    instance = Value("x")
    container.add_singleton(instance)

    assert container.get(Value) is instance


def test_missing_service_raises_lookup_error() -> None:
    with pytest.raises(LookupError, match="не зарегистрирован"):
        ServiceContainer().get(Value)


def test_try_get_returns_none_for_missing() -> None:
    assert ServiceContainer().try_get(Value) is None


def test_factory_is_cached() -> None:
    container = ServiceContainer()
    calls: list[int] = []

    def make() -> Value:
        calls.append(1)
        return Value("factory")

    container.add_singleton_factory(make, Value)

    assert container.get(Value).value == "factory"
    assert container.get(Value).value == "factory"
    assert len(calls) == 1


def test_factory_with_container_argument() -> None:
    container = ServiceContainer()
    container.add_singleton(Value("dep"))

    def make(sp: ServiceContainer) -> str:
        return sp.get(Value).value + "!"

    container.add_singleton_factory(make, str)

    assert container.get(str) == "dep!"


def test_factory_type_from_return_annotation() -> None:
    container = ServiceContainer()

    def make() -> int:
        return 42

    container.add_singleton_factory(make)

    assert container.get(int) == 42


def test_factory_without_type_raises() -> None:
    container = ServiceContainer()

    with pytest.raises(ValueError, match="service_type"):
        container.add_singleton_factory(lambda: 1)  # type: ignore[arg-type]


def test_create_services_registers_config_instance(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "CONFIG_DIR", tmp_path)
    config = ZereConfig()

    container = create_services(config)

    assert container.get(ZereConfig) is config
    assert isinstance(container.get(PluginConfig), PluginConfig)
    # Незарегистрированный сервис по-прежнему честно отсутствует.
    assert container.try_get(Value) is None


class NullContainer:
    def get(self, service_type: Any) -> Any:
        return None


def test_jev_router_failure_falls_back_and_is_logged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Битые настройки Jev → ни исключения, ни NameError, запись в errors.log."""
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path)

    import zere.core.handlers.jev_routing_handler as jev_module

    def boom(**kwargs: Any) -> Any:
        raise RuntimeError("битые настройки роутера")

    monkeypatch.setattr(jev_module, "build_jev_handler", boom)

    assert services._create_jev_handler(NullContainer(), []) is None

    log = (tmp_path / "errors.log").read_text(encoding="utf-8")
    assert "роутер интентов Jev не подключён" in log
    assert "битые настройки роутера" in log


def test_jev_handler_success_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Успешная сборка возвращает обработчик, а не None."""
    import zere.core.handlers.jev_routing_handler as jev_module

    marker = object()
    monkeypatch.setattr(jev_module, "build_jev_handler", lambda **kwargs: marker)

    assert services._create_jev_handler(NullContainer(), []) is marker
