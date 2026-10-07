"""Порт ZERE.Core/ServiceRegistration.cs — мини DI-контейнер.

Замена Microsoft.Extensions.DependencyInjection:
  ServiceCollection.AddSingleton(...) / GetRequiredService<T>() →
  ServiceContainer.add_singleton(...) / get(cls).
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional, Type, TypeVar

from zere.ai.ai_service import AiService
from zere.ai.ollama_client import OllamaClient
from zere.core.ai.context_builder import ContextBuilder
from zere.core.configuration.zere_config import ZereConfig
from zere.core.context.runtime_context import RuntimeContext
from zere.core.dependencies.dependency_checker import DependencyChecker
from zere.core.engine import ZereEngine
from zere.core.handlers.ai_handler import AIHandler
from zere.core.handlers.conversation_handler import ConversationHandler
from zere.core.handlers.drawing_handler import DrawingHandler
from zere.core.handlers.file_handler import FileHandler
from zere.core.handlers.game_handler import GameHandler
from zere.core.handlers.handler_pipeline import HandlerPipeline
from zere.core.handlers.i_zere_handler import IZereHandler
from zere.core.handlers.memory_extractor import MemoryExtractor
from zere.core.handlers.memory_handler import MemoryHandler
from zere.core.handlers.memory_query_handler import MemoryQueryHandler
from zere.core.handlers.process_handler import ProcessHandler
from zere.core.handlers.volume_handler import VolumeHandler
from zere.core.handlers.windows_handler import WindowsHandler
from zere.core.logging.log_service import LogService
from zere.core.plugins.plugin_config import PluginConfig
from zere.core.plugins.plugin_manager import PluginManager
from zere.memory.database.conversation_repository import ConversationRepository
from zere.memory.database.memory_database import MemoryDatabase
from zere.memory.database.memory_repository import MemoryRepository
from zere.tools.applications.application_launcher import ApplicationLauncher
from zere.tools.drawing.drawing_service import DrawingService
from zere.tools.files.file_manager import FileManager
from zere.tools.gaming.game_guardian import GameGuardian
from zere.tools.gaming.game_tracker import GameTracker
from zere.tools.windows.process_service import ProcessService
from zere.tools.windows.safe_action_manager import SafeActionManager
from zere.tools.windows.volume.volume_service import VolumeService

T = TypeVar("T")

Factory = Callable[["ServiceContainer"], Any]


class ServiceContainer:
    """Мини-контейнер: синглтоны + фабрики с кэшированием."""

    def __init__(self) -> None:
        self._instances: Dict[Type[Any], Any] = {}
        self._factories: Dict[Type[Any], Factory] = {}

    def add_singleton(self, instance: Any) -> None:
        self._instances[type(instance)] = instance

    def add_singleton_factory(
        self,
        factory: Callable[..., Any],
        service_type: Optional[Type[T]] = None,
    ) -> None:
        """Регистрация фабрики.

        service_type необязателен: если не указан, берётся аннотация
        возвращаемого типа фабрики (лямбды аннотации не имеют —
        для них service_type обязателен).
        """
        key: Optional[Type[Any]] = service_type

        if key is None:
            try:
                return_annotation = inspect.signature(factory).return_annotation
            except (TypeError, ValueError):
                return_annotation = inspect.Signature.empty
            if isinstance(return_annotation, type):
                key = return_annotation

        if key is None:
            raise ValueError(
                "add_singleton_factory: не удалось определить тип сервиса — "
                "укажите service_type или аннотацию возвращаемого типа"
            )

        def wrapped(container: "ServiceContainer") -> Any:
            return ServiceContainer._invoke(factory, container)

        self._factories[key] = wrapped

    @staticmethod
    def _invoke(factory: Callable[..., Any], container: "ServiceContainer") -> Any:
        """Вызывает фабрику: sp => ... принимает контейнер, () => ... без аргументов."""
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            return factory()

        positional = [
            p
            for p in signature.parameters.values()
            if p.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL
            for p in signature.parameters.values()
        )

        if positional or has_varargs:
            return factory(container)

        return factory()

    def get(self, service_type: Type[T]) -> T:
        """GetRequiredService<T>: кэширует, при отсутствии вызывает фабрику."""
        if service_type in self._instances:
            return self._instances[service_type]

        factory = self._factories.get(service_type)
        if factory is not None:
            instance = factory(self)
            self._instances[service_type] = instance
            return instance

        raise LookupError(
            f"Сервис {service_type.__name__} не зарегистрирован в ServiceContainer"
        )

    def try_get(self, service_type: Type[T]) -> Optional[T]:
        try:
            return self.get(service_type)
        except LookupError:
            return None


def create_services(config: ZereConfig) -> ServiceContainer:
    """Порт ServiceRegistration.Create(config) — порядок и фабрики дословно.

    Config передаётся вызывающей стороной, чтобы консоль и DI работали
    с одним инстансом (паритет с C#: два разных Load() создавали два
    конфига, POST /api/config не достиг бы ядра).
    """

    services = ServiceContainer()

    # services.AddSingleton(config);
    services.add_singleton(config)

    # var pluginConfig = PluginConfig.Load(); services.AddSingleton(pluginConfig);
    services.add_singleton(PluginConfig.load())

    # services.AddSingleton<LogService>();
    services.add_singleton_factory(lambda sp: LogService(), LogService)

    # services.AddSingleton<MemoryDatabase>();
    services.add_singleton_factory(lambda sp: MemoryDatabase(), MemoryDatabase)

    # services.AddSingleton<MemoryRepository>();
    services.add_singleton_factory(
        lambda sp: MemoryRepository(sp.get(MemoryDatabase)), MemoryRepository
    )

    # services.AddSingleton<ConversationRepository>();
    services.add_singleton_factory(
        lambda sp: ConversationRepository(sp.get(MemoryDatabase)), ConversationRepository
    )

    # services.AddSingleton<OllamaClient>(sp => new OllamaClient(cfg.Model, cfg.OllamaTimeoutMinutes));
    def _create_ollama_client(sp: ServiceContainer) -> OllamaClient:
        cfg = sp.get(ZereConfig)
        return OllamaClient(
            cfg.Model,
            cfg.OllamaTimeoutMinutes,
            keep_alive=cfg.LlmKeepAlive,
            timeout_seconds=cfg.LlmTimeoutSeconds,
        )

    services.add_singleton_factory(_create_ollama_client, OllamaClient)

    # services.AddSingleton<AiService>(); — выбор провайдера ИИ: облачный
    # ключ пользователя (config/ai.json) → локальная модель (Ollama).
    # Панель меняет настройки на лету: прокси читает их на каждый запрос.
    services.add_singleton_factory(
        lambda sp: AiService(config=sp.get(ZereConfig)), AiService
    )

    # services.AddSingleton<RuntimeContext>(); — флаги рантайма (этап 1, S5)
    services.add_singleton_factory(lambda sp: RuntimeContext(), RuntimeContext)

    # services.AddSingleton<ContextBuilder>();
    services.add_singleton_factory(
        lambda sp: ContextBuilder(sp.get(MemoryRepository), sp.get(ConversationRepository)),
        ContextBuilder,
    )

    # services.AddSingleton<MemoryExtractor>();
    services.add_singleton_factory(
        lambda sp: MemoryExtractor(sp.get(MemoryRepository), sp.get(ZereConfig)),
        MemoryExtractor,
    )

    # services.AddSingleton<PluginManager>(sp => { pm.LoadAll(); pm.SetActivePersonality(...); });
    def _create_plugin_manager(sp: ServiceContainer) -> PluginManager:
        pm = PluginManager()
        pm.load_all()
        pc = sp.get(PluginConfig)
        pm.set_active_personality(pc.ActivePersonalityId, pc.ActivePersonalityStyle)
        return pm

    services.add_singleton_factory(_create_plugin_manager, PluginManager)

    # services.AddSingleton<DependencyChecker>();
    services.add_singleton_factory(
        lambda sp: DependencyChecker(sp.get(ZereConfig)), DependencyChecker
    )

    # services.AddSingleton<ProcessService>();
    services.add_singleton_factory(lambda sp: ProcessService(), ProcessService)

    # services.AddSingleton<ApplicationLauncher>();
    services.add_singleton_factory(lambda sp: ApplicationLauncher(), ApplicationLauncher)

    # services.AddSingleton<VolumeService>();
    services.add_singleton_factory(lambda sp: VolumeService(), VolumeService)

    # services.AddSingleton<GameGuardian>();
    services.add_singleton_factory(lambda sp: GameGuardian(), GameGuardian)

    # services.AddSingleton<GameTracker>();
    services.add_singleton_factory(lambda sp: GameTracker(), GameTracker)

    # services.AddSingleton<FileManager>();
    services.add_singleton_factory(lambda sp: FileManager(), FileManager)

    # services.AddSingleton<DrawingService>();
    services.add_singleton_factory(lambda sp: DrawingService(), DrawingService)

    # services.AddSingleton<SafeActionManager>();
    services.add_singleton_factory(
        lambda sp: SafeActionManager(sp.get(ProcessService), sp.get(FileManager)),
        SafeActionManager,
    )

    # services.AddSingleton<MemoryHandler>();
    services.add_singleton_factory(
        lambda sp: MemoryHandler(sp.get(MemoryRepository)), MemoryHandler
    )

    # services.AddSingleton<MemoryQueryHandler>();
    services.add_singleton_factory(
        lambda sp: MemoryQueryHandler(sp.get(MemoryRepository)), MemoryQueryHandler
    )

    # services.AddSingleton<ConversationHandler>();
    services.add_singleton_factory(
        lambda sp: ConversationHandler(sp.get(ConversationRepository)), ConversationHandler
    )

    # services.AddSingleton<ProcessHandler>();
    services.add_singleton_factory(
        lambda sp: ProcessHandler(sp.get(ProcessService), sp.get(SafeActionManager)),
        ProcessHandler,
    )

    # services.AddSingleton<WindowsHandler>();
    services.add_singleton_factory(
        lambda sp: WindowsHandler(sp.get(ApplicationLauncher), sp.get(SafeActionManager)),
        WindowsHandler,
    )

    # services.AddSingleton<FileHandler>();
    services.add_singleton_factory(
        lambda sp: FileHandler(sp.get(FileManager), sp.get(SafeActionManager)),
        FileHandler,
    )

    # services.AddSingleton<GameHandler>();
    services.add_singleton_factory(
        lambda sp: GameHandler(sp.get(GameGuardian), sp.get(GameTracker)), GameHandler
    )

    # services.AddSingleton<VolumeHandler>();
    services.add_singleton_factory(
        lambda sp: VolumeHandler(sp.get(VolumeService)), VolumeHandler
    )

    # services.AddSingleton<DrawingHandler>();
    services.add_singleton_factory(
        lambda sp: DrawingHandler(sp.get(DrawingService)), DrawingHandler
    )

    # services.AddSingleton<AIHandler>();
    # Первый аргумент — прокси выбора провайдера (облачный ключ или локальная
    # модель): интерфейс generate/warmup/close тот же, что у OllamaClient,
    # поэтому AIHandler и голосовой режим менять не пришлось.
    services.add_singleton_factory(
        lambda sp: AIHandler(
            sp.get(AiService).proxy,
            sp.get(ContextBuilder),
            sp.get(PluginManager),
            runtime=sp.get(RuntimeContext),
            config=sp.get(ZereConfig),
        ),
        AIHandler,
    )

    # services.AddSingleton<HandlerPipeline>(sp => new HandlerPipeline(10 хэндлеров));
    def _create_handler_pipeline(sp: ServiceContainer) -> HandlerPipeline:
        handlers = [
            sp.get(MemoryHandler),
            sp.get(MemoryQueryHandler),
            sp.get(ConversationHandler),
            sp.get(ProcessHandler),
            sp.get(WindowsHandler),
            sp.get(FileHandler),
            sp.get(GameHandler),
            sp.get(VolumeHandler),
            # Рисование — перед AIHandler: «нарисуй круг» не должно уходить в LLM.
            sp.get(DrawingHandler),
            sp.get(AIHandler),
        ]  # type: List[IZereHandler]

        return HandlerPipeline(handlers)

    services.add_singleton_factory(_create_handler_pipeline, HandlerPipeline)

    # services.AddSingleton<ZereEngine>();
    services.add_singleton_factory(
        lambda sp: ZereEngine(
            sp.get(HandlerPipeline),
            sp.get(MemoryExtractor),
            sp.get(PluginManager),
            sp.get(ConversationRepository),
        ),
        ZereEngine,
    )

    return services
