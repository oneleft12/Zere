using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class MemoryHandler : IJarvisHandler
{
    private readonly MemoryRepository _memory = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower.StartsWith("запомни") ||
               lower.StartsWith("обнови память") ||
               lower.StartsWith("забудь") ||
               lower == "покажи память" ||
               lower == "очисти память";
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        // ===== ПОКАЗАТЬ ПАМЯТЬ =====

        if (lower == "покажи память")
        {
            var memories = _memory.GetAll();

            if (memories.Count == 0)
                return "Я пока ничего не запомнил.";

            return "Вот что я помню:\n\n" +
                   string.Join("\n",
                       memories.Select(m => $"• {m.Key} = {m.Value}"));
        }

        // ===== ОЧИСТИТЬ ПАМЯТЬ =====

        if (lower == "очисти память")
        {
            _memory.Clear();
            return "Память полностью очищена.";
        }

        // ===== ЗАБЫТЬ =====

        if (lower.StartsWith("забудь "))
        {
            var key = lower["забудь ".Length..].Trim();

            var deleted = _memory.Forget(key);

            return deleted
                ? $"Я забыл информацию: {key}."
                : $"Я не нашёл запись «{key}».";
        }

        // ===== ОБНОВИТЬ ПАМЯТЬ =====

        if (lower.StartsWith("обнови память "))
        {
            var text = message["обнови память ".Length..].Trim();

            if (!text.Contains('='))
                return "Например: обнови память проект = AI VOCALPLUS";

            var parts = text.Split('=', 2);

            var key = parts[0].Trim().ToLower();
            var value = parts[1].Trim();

            _memory.Remember(key, value);

            return $"Память обновлена: {key} = {value}";
        }

        // ===== ЗАПОМНИ =====

        var textToRemember = message["запомни".Length..].Trim();

        foreach (var prefix in new[] { "мое ", "мой ", "моя ", "что " })
        {
            if (textToRemember.StartsWith(prefix,
                    StringComparison.OrdinalIgnoreCase))
            {
                textToRemember = textToRemember[prefix.Length..].Trim();
                break;
            }
        }

        string memoryKey;
        string memoryValue;

        if (textToRemember.Contains('='))
        {
            var parts = textToRemember.Split('=', 2);

            memoryKey = parts[0].Trim().ToLower();
            memoryValue = parts[1].Trim();
        }
        else
        {
            var words = textToRemember.Split(
                ' ',
                StringSplitOptions.RemoveEmptyEntries);

            if (words.Length < 2)
                return "Например: запомни имя Dan";

            memoryKey = words[0].Trim().ToLower();
            memoryValue = string.Join(" ", words.Skip(1));
        }

        _memory.Remember(memoryKey, memoryValue);

        return $"Запомнил: {memoryKey} = {memoryValue}";
    }
}