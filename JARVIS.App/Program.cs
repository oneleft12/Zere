using JARVIS.Core;
using JARVIS.Core.Configuration;
using JARVIS.Core.Dependencies;
using JARVIS.Core.Logging;
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

while (true)
{
    Console.Write("Вы: ");

    var message = Console.ReadLine();

    if (string.IsNullOrWhiteSpace(message))
        continue;

    if (message.ToLower() == "exit")
        break;
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