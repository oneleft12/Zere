using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class ConversationHandler
{
    private readonly ConversationRepository _history = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower == "покажи историю" ||
               lower == "очисти историю";
    }

    public string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        if (lower == "очисти историю")
        {
            _history.ClearHistory();
            return "История диалога очищена.";
        }

        var history = _history.GetLast(10);

        if (history.Count == 0)
            return "История пока пуста.";

        return string.Join(
            "\n\n",
            history.Select(h =>
                $"Вы: {h.UserMessage}\nJARVIS: {h.JarvisResponse}")
        );
    }
}