using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class MemoryHandler
{
    private readonly MemoryRepository _memory = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower();

        return lower.StartsWith("запомни") ||
               lower == "покажи память" ||
               lower == "что ты знаешь обо мне" ||
               lower == "очисти память";
    }

    public string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        // ===== ПОКАЗАТЬ ПАМЯТЬ =====
        if (lower == "покажи память" ||
            lower == "что ты знаешь обо мне")
        {
            var memories = _memory.GetAll();

            if (memories.Count == 0)
                return "Я пока ничего не запомнил.";

            return "Вот что я помню:\n\n" +
                   string.Join("\n",
                       memories.Select(x => $"• {x.Key} = {x.Value}"));
        }

        // ===== ОЧИСТИТЬ =====
        if (lower == "очисти память")
        {
            _memory.Clear();

            return "Память очищена.";
        }

        // ===== ЗАПОМНИ =====
        var text = message.Substring("запомни".Length).Trim();

        foreach (var prefix in new[] { "мое ", "мой ", "моя ", "что " })
        {
            if (text.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                text = text.Substring(prefix.Length);
                break;
            }
        }

        string key;
        string value;

        if (text.Contains('='))
        {
            var parts = text.Split('=', 2);

            key = parts[0].Trim().ToLower();
            value = parts[1].Trim();
        }
        else
        {
            var words = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);

            if (words.Length < 2)
                return "Например: запомни мое имя Dan";

            key = words[0].Trim().ToLower();
            value = string.Join(" ", words.Skip(1));
        }

        _memory.Remember(key, value);

        return $"Запомнил: {key} = {value}";
    }
}