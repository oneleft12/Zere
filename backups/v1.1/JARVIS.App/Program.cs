using JARVIS.Core;

Console.WriteLine("""
=================================
          J A R V I S
=================================
""");

Console.WriteLine("Локальный ИИ подключён.");
Console.WriteLine("Введите 'exit' для выхода.\n");

var jarvis = new JarvisEngine();

while (true)
{
    Console.Write("Вы: ");

    var message = Console.ReadLine();

    if (string.IsNullOrWhiteSpace(message))
        continue;

    if (message.Equals("exit", StringComparison.OrdinalIgnoreCase))
        break;

    try
    {
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