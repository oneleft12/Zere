using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class MemoryHandler : IJarvisHandler
{
    private readonly MemoryRepository _memory;

    public MemoryHandler(MemoryRepository memory)
    {
        _memory = memory;
    }

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower.StartsWith("запомни") ||
               lower.StartsWith("сохрани") ||
               lower.StartsWith("не забудь") ||
               lower.StartsWith("запиши") ||
               lower.StartsWith("remember") ||
               lower.StartsWith("обнови память") ||
               lower.StartsWith("измени память") ||
               lower.StartsWith("забудь") ||
               lower.StartsWith("забыть") ||
               lower.StartsWith("очисти запись") ||
               lower.StartsWith("удали из памяти") ||
               lower == "покажи память" ||
               lower == "что ты помнишь" ||
               lower == "что помнишь" ||
               lower == "воспоминания" ||
               lower == "все воспоминания" ||
               lower == "память" ||
               lower == "очисти память" ||
               lower == "очистить память" ||
               lower == "сбрось память" ||
               lower == "reset memory";
    }

    public Task<string?> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        // === Показать память ===
        if (lower == "покажи память" ||
            lower == "что ты помнишь" ||
            lower == "что помнишь" ||
            lower == "воспоминания" ||
            lower == "все воспоминания" ||
            lower == "память")
        {
            var memories = _memory.GetAll();

            if (memories.Count == 0)
                return "Я пока ничего не запомнил.";

            return "Вот что я помню:\n\n" +
                   string.Join("\n",
                       memories.Select(m => $"• {m.Key} = {m.Value}"));
        }

        // === Очистить память ===
        if (lower == "очисти память" ||
            lower == "очистить память" ||
            lower == "сбрось память" ||
            lower == "reset memory")
        {
            _memory.Clear();
            return "Память полностью очищена.";
        }

        // === Забыть конкретное ===
        if (lower.StartsWith("забудь ") || lower.StartsWith("забыть "))
        {
            var key = lower.Contains("забудь ")
                ? lower["забудь ".Length..].Trim()
                : lower["забыть ".Length..].Trim();

            var deleted = _memory.Forget(key);

            return deleted
                ? $"Я забыл информацию: {key}."
                : $"Я не нашёл запись «{key}».";
        }

        if (lower.StartsWith("очисти запись "))
        {
            var key = lower["очисти запись ".Length..].Trim();
            var deleted = _memory.Forget(key);
            return deleted
                ? $"Запись «{key}» удалена из памяти."
                : $"Запись «{key}» не найдена.";
        }

        if (lower.StartsWith("удали из памяти "))
        {
            var key = lower["удали из памяти ".Length..].Trim();
            var deleted = _memory.Forget(key);
            return deleted
                ? $"Удалил из памяти: {key}."
                : $"Не нашёл в памяти: «{key}».";
        }

        if (lower.StartsWith("забудь") || lower.StartsWith("забыть"))
        {
            return "Укажите, что забыть. Например: забудь имя";
        }

        // === Обновить память ===
        if (lower.StartsWith("обнови память ") || lower.StartsWith("измени память "))
        {
            var prefix = lower.StartsWith("обнови память ") ? "обнови память " : "измени память ";
            var text = message[prefix.Length..].Trim();

            if (!text.Contains('='))
                return "Например: обнови память проект = AI VOCALPLUS";

            var parts = text.Split('=', 2);

            var key = parts[0].Trim().ToLower();
            var value = parts[1].Trim();

            _memory.Remember(key, value);

            return $"Память обновлена: {key} = {value}";
        }

        // === Запомнить ===
        var textToRemember = "";

        if (lower.StartsWith("запомни"))
            textToRemember = message["запомни".Length..].Trim();
        else if (lower.StartsWith("сохрани"))
            textToRemember = message["сохрани".Length..].Trim();
        else if (lower.StartsWith("не забудь"))
            textToRemember = message["не забудь".Length..].Trim();
        else if (lower.StartsWith("запиши"))
            textToRemember = message["запиши".Length..].Trim();
        else if (lower.StartsWith("remember"))
            textToRemember = message["remember".Length..].Trim();

        if (string.IsNullOrWhiteSpace(textToRemember))
            return "Укажите, что запомнить. Например: запомни имя Dan";

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
