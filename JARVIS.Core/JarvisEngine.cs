using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class ConversationHandler : IJarvisHandler
{
    private readonly ConversationRepository _conversations = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower == "покажи историю" ||
               lower == "история" ||
               lower == "очисти историю";
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        // ===== ПОКАЗАТЬ ИСТОРИЮ =====

        if (lower == "покажи историю" || lower == "история")
        {
            var history = _conversations.GetLast(20);

            if (history.Count == 0)
                return "История пуста.";

            return string.Join(
                "\n\n",
                history.Select(h =>
                    $"Вы: {h.UserMessage}\nJARVIS: {h.JarvisResponse}"));
        }

        // ===== ОЧИСТИТЬ ИСТОРИЮ =====

        if (lower == "очисти историю")
        {
            _conversations.Clear();
            return "История очищена.";
        }

        return "Команда истории не распознана.";
    }
}