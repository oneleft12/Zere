using ZERE.AI;
using ZERE.Core.AI;
using ZERE.Core.Configuration;
using ZERE.Core.Context;
using ZERE.Core.Dependencies;
using ZERE.Core.Handlers;
using ZERE.Core.Logging;
using ZERE.Core.Plugins;
using ZERE.Memory.Database;
using ZERE.Tools.Applications;
using ZERE.Tools.Files;
using ZERE.Tools.Gaming;
using ZERE.Tools.Windows;
using ZERE.Tools.Windows.Processes;
using ZERE.Tools.Windows.Volume;
using Microsoft.Extensions.DependencyInjection;

namespace ZERE.Core;

public static class ServiceRegistration
{
    /// <summary>
    /// Регистрация сервисов. Config передаётся вызывающей стороной,
    /// чтобы Program и DI работали с одним инстансом (раньше Load()
    /// вызывался дважды и создавал два разных конфига).
    /// </summary>
    public static IServiceProvider Create(ZereConfig config)
    {
        var services = new ServiceCollection();

        services.AddSingleton(config);

        var pluginConfig = PluginConfig.Load();
        services.AddSingleton(pluginConfig);

        services.AddSingleton<LogService>();

        services.AddSingleton<MemoryDatabase>();
        services.AddSingleton<MemoryRepository>();
        services.AddSingleton<ConversationRepository>();

        services.AddSingleton(sp =>
        {
            var cfg = sp.GetRequiredService<ZereConfig>();
            return new OllamaClient(
                cfg.Model,
                cfg.OllamaTimeoutMinutes,
                cfg.LlmKeepAlive,
                cfg.LlmTimeoutSeconds);
        });

        // Флаги рантайма (голосовой режим и т.п.) — анализ S5.
        services.AddSingleton<RuntimeContext>();

        services.AddSingleton<ContextBuilder>();
        services.AddSingleton<MemoryExtractor>();

        services.AddSingleton<PluginManager>(sp =>
        {
            var pm = new PluginManager();
            pm.LoadAll();
            var pc = sp.GetRequiredService<PluginConfig>();
            pm.SetActivePersonality(pc.ActivePersonalityId, pc.ActivePersonalityStyle);
            return pm;
        });

        services.AddSingleton<DependencyChecker>();

        services.AddSingleton<ProcessService>();
        services.AddSingleton<ApplicationLauncher>();
        services.AddSingleton<VolumeService>();
        services.AddSingleton<GameGuardian>();
        services.AddSingleton<GameTracker>();
        services.AddSingleton<FileManager>();
        services.AddSingleton<SafeActionManager>();

        services.AddSingleton<MemoryHandler>();
        services.AddSingleton<MemoryQueryHandler>();
        services.AddSingleton<ConversationHandler>();
        services.AddSingleton<ProcessHandler>();
        services.AddSingleton<WindowsHandler>();
        services.AddSingleton<FileHandler>();
        services.AddSingleton<GameHandler>();
        services.AddSingleton<VolumeHandler>();
        services.AddSingleton<AIHandler>();

        services.AddSingleton<HandlerPipeline>(sp =>
        {
            var handlers = new IZereHandler[]
            {
                sp.GetRequiredService<MemoryHandler>(),
                sp.GetRequiredService<MemoryQueryHandler>(),
                sp.GetRequiredService<ConversationHandler>(),
                sp.GetRequiredService<ProcessHandler>(),
                sp.GetRequiredService<WindowsHandler>(),
                sp.GetRequiredService<FileHandler>(),
                sp.GetRequiredService<GameHandler>(),
                sp.GetRequiredService<VolumeHandler>(),
                sp.GetRequiredService<AIHandler>()
            };

            return new HandlerPipeline(handlers);
        });

        services.AddSingleton<ZereEngine>();

        return services.BuildServiceProvider();
    }
}
