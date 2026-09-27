using JARVIS.AI;
using JARVIS.Core.AI;
using JARVIS.Core.Configuration;
using JARVIS.Core.Dependencies;
using JARVIS.Core.Handlers;
using JARVIS.Core.Logging;
using JARVIS.Core.Plugins;
using JARVIS.Memory.Database;
using JARVIS.Tools.Applications;
using JARVIS.Tools.Files;
using JARVIS.Tools.Gaming;
using JARVIS.Tools.Windows;
using JARVIS.Tools.Windows.Processes;
using JARVIS.Tools.Windows.Volume;
using Microsoft.Extensions.DependencyInjection;

namespace JARVIS.Core;

public static class ServiceRegistration
{
    /// <summary>
    /// Регистрация сервисов. Config передаётся вызывающей стороной,
    /// чтобы Program и DI работали с одним инстансом (раньше Load()
    /// вызывался дважды и создавал два разных конфига).
    /// </summary>
    public static IServiceProvider Create(JarvisConfig config)
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
            var cfg = sp.GetRequiredService<JarvisConfig>();
            return new OllamaClient(cfg.Model, cfg.OllamaTimeoutMinutes);
        });

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
            var handlers = new IJarvisHandler[]
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

        services.AddSingleton<JarvisEngine>();

        return services.BuildServiceProvider();
    }
}
