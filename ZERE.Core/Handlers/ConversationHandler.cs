using ZERE.Memory.Database;

namespace ZERE.Core.Handlers;

public class ConversationHandler : IZereHandler
{
    private readonly ConversationRepository _conversations;

    public ConversationHandler(ConversationRepository conversations)
    {
        _conversations = conversations;
    }

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower == "покажи историю" ||
               lower == "история" ||
               lower == "история разговоров" ||
               lower == "наши диалоги" ||
               lower == "диалоги" ||
               lower == "разговоры" ||
               lower == "что мы обсуждали" ||
               lower == "о чём мы говорили" ||
               lower == "история чата" ||
               lower == "очисти историю" ||
               lower == "очисти диалоги" ||
               lower == "очисть разговоры" ||
               lower == "сбрось историю";
    }

    public Task<string?> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
    {
        var lower = message.ToLower().Trim();

        // === Показать историю ===
        if (lower == "покажи историю" ||
            lower == "история" ||
            lower == "история разговоров" ||
            lower == "наши диалоги" ||
            lower == "диалоги" ||
            lower == "разговоры" ||
            lower == "что мы обсуждали" ||
            lower == "о чём мы говорили" ||
            lower == "история чата")
        {
            var history = _conversations.GetLast(20);

            if (history.Count == 0)
                return "История пуста.";

            return string.Join(
                "\n\n",
                history.Select(h =>
                    $"Вы: {h.UserMessage}\nZERE: {h.ZereResponse}"));
        }

        // === Очистить историю ===
        if (lower == "очисти историю" ||
            lower == "очисти диалоги" ||
            lower == "очисть разговоры" ||
            lower == "сбрось историю")
        {
            _conversations.ClearHistory();
            return "История очищена.";
        }

        return "Команда истории не распознана.";
    }
}
