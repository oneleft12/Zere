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

    public string BuildMemory()
    {
        var memories = _memory.GetAll();

        if (memories.Count == 0)
            return "";

        var sb = new StringBuilder();

        foreach (var item in memories)
            sb.AppendLine($"{item.Key}: {item.Value}");

        return sb.ToString();
    }

    public string BuildHistory(int count = 5)
    {
        var history = _history.GetLast(count);

        if (history.Count == 0)
            return "";

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
