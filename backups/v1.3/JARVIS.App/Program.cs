using JARVIS.Core;
using JARVIS.Memory.Database;

Console.WriteLine("""
=================================
        J A R V I S
=================================
""");

Console.WriteLine("JARVIS OS v1.3.2 STABLE");
Console.WriteLine("SQLite Memory Engine подключён.");
Console.WriteLine("Введите 'exit' для выхода.\n");

// Создаём базу автоматически
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
        // ВСЕ сообщения проходят через ProcessAsync()
        var answer = await jarvis.ProcessAsync(message);

        Console.WriteLine();
        Console.WriteLine($"JARVIS: {answer}");
        Console.WriteLine();
    }
    catch (Exception ex)
    {
        Console.WriteLine();
        Console.WriteLine($"Ошибка: {ex.Message}");
        Console.WriteLine();
    }
}