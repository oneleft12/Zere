using JARVIS.Core;
using JARVIS.Core.Configuration;
using JARVIS.Core.Dependencies;
using JARVIS.Core.Logging;
using JARVIS.Core.Plugins;
using JARVIS.Core.Plugins.Settings;
using JARVIS.Memory.Database;

var config = JarvisConfig.Load();
var logger = new LogService();

logger.Info($"{config.AssistantName} OS {config.Version} запускается.");

Console.WriteLine($"""
=================================
        {config.AssistantName}
=================================

Версия: {config.Version}
Модель: {config.Model}
Язык: {config.Language}

""");

var checker = new DependencyChecker(config);
var results = checker.RunAll();
checker.PrintReport();

if (!checker.AllCriticalPassed())
{
    checker.OfferInstall();
}

if (!checker.AllCriticalPassed())
{
    Console.WriteLine("Критические зависимости не выполнены.");
    Console.WriteLine("Устраните ошибки выше и запустите снова.");
    Console.WriteLine("Нажмите Enter для выхода...");
    Console.ReadLine();
    return;
}

Console.WriteLine("Все зависимости в порядке.\n");

_ = new MemoryDatabase();

var jarvis = new JarvisEngine();

var activePersonality = jarvis.PluginManager.ActivePersonality;
if (activePersonality != null)
{
    Console.WriteLine($"[Личность] {activePersonality.Name} | Стиль: {activePersonality.Style}\n");
}

Console.WriteLine("Команды: 'настройки' — панель настроек, 'exit' — выход\n");

while (true)
{
    Console.Write("Вы: ");

    var message = Console.ReadLine();

    if (string.IsNullOrWhiteSpace(message))
        continue;

    if (message.ToLower() == "exit")
        break;

    if (message.ToLower() == "настройки" || message.ToLower() == "settings")
    {
        var settingsMenu = new SettingsMenu(jarvis.PluginManager, jarvis.Config);
        settingsMenu.Show();

        activePersonality = jarvis.PluginManager.ActivePersonality;
        if (activePersonality != null)
        {
            Console.WriteLine($"\n[Личность] {activePersonality.Name} | Стиль: {activePersonality.Style}\n");
        }
        continue;
    }

    try
    {
        var answer = await jarvis.ProcessAsync(message);

        logger.Info($"JARVIS: {answer}");

        Console.WriteLine();
        Console.WriteLine($"JARVIS: {answer}");
        Console.WriteLine();
    }
    catch (Exception ex)
    {
        logger.Error(ex.Message);

        Console.WriteLine();
        Console.WriteLine($"Ошибка: {ex.Message}");
        Console.WriteLine();
    }
}

logger.Info("JARVIS завершил работу.");
