using JARVIS.Core;
using JARVIS.Core.Configuration;
using JARVIS.Core.Logging;
using JARVIS.Memory.Database;

var config = JarvisConfig.Load();
var logger = new LogService();

logger.Info($"{config.AssistantName} OS {config.Version} запускается.");

_ = new MemoryDatabase();

Console.WriteLine($"""
=================================
        {config.AssistantName}
=================================

Версия: {config.Version}
Модель: {config.Model}
Язык: {config.Language}

SQLite Memory Engine подключён.
Введите 'exit' для выхода.

""");

var jarvis = new JarvisEngine();

while (true)
{
    Console.Write("Вы: ");

    var message = Console.ReadLine();

    if (string.IsNullOrWhiteSpace(message))
        continue;

    if (message.ToLower() == "exit")
        break;

    logger.Info($"Пользователь: {message}");

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