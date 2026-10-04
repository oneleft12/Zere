using JARVIS.Memory.Database;
using System.Text;

namespace JARVIS.Core.AI;

public class ContextBuilder
{
    private readonly MemoryRepository _memory;
    private readonly ConversationRepository _history;

    public ContextBuilder(MemoryRepository memory, ConversationRepository history)
    {
        _memory = memory;
        _history = history;
    }

    // Анализ S5: память без лимита уплывала в промпт целиком — промпт
    // рос, инференс замедлялся, контекст (num_ctx) переполнялся.
    private const int MaxMemoryItems = 30;
    private const int MaxMemoryChars = 1500;

    public string BuildMemory()
    {
        var memories = _memory.GetAll();

        if (memories.Count == 0)
            return "";

        var sb = new StringBuilder();
        var used = 0;
        var items = 0;
        var truncated = false;

        foreach (var item in memories)
        {
            if (items >= MaxMemoryItems)
            {
                truncated = true;
                break;
            }

            var line = $"{item.Key}: {item.Value}";

            if (used + line.Length > MaxMemoryChars)
            {
                truncated = true;
                break;
            }

            sb.AppendLine(line);
            used += line.Length;
            items++;
        }

        if (truncated)
            sb.AppendLine("… (часть воспоминаний опущена — лимит контекста)");

        return sb.ToString();
    }

    public string BuildHistory(int count = 5)
    {
        var history = _history.GetLast(count);

        if (history.Count == 0)
            return "";

        // GetLast отдаёт новые первыми (ORDER BY Id DESC) — для контекста
        // диалог должен читаться от старых сообщений к новым.
        history.Reverse();

        var sb = new StringBuilder();

        foreach (var item in history)
        {
            sb.AppendLine($"Пользователь: {item.UserMessage}");
            sb.AppendLine($"Ассистент: {item.JarvisResponse}");
            sb.AppendLine();
        }

        return sb.ToString();
    }
}
