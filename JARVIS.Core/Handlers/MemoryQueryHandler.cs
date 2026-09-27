using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class MemoryQueryHandler : IJarvisHandler
{
    private readonly MemoryRepository _memory;

    public MemoryQueryHandler(MemoryRepository memory)
    {
        _memory = memory;
    }

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower.Contains("как меня зовут") ||
               lower.Contains("какой у меня проект") ||
               lower.Contains("что ты знаешь обо мне") ||
               lower.Contains("какая у меня видеокарта") ||
               lower.Contains("какая у меня windows") ||
               lower.StartsWith("что такое ") ||
               lower.StartsWith("кто такой ") ||
               lower.StartsWith("кто такая ") ||
               lower.StartsWith("что значит ") ||
               lower.StartsWith("расскажи про ") ||
               lower.StartsWith("расскажи о ");
    }

    public Task<string?> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string? Handle(string message)
    {
        var lower = message.ToLower().Trim();

        if (lower.Contains("что ты знаешь обо мне"))
        {
            var all = _memory.GetAll();

            if (all.Count == 0)
                return "Я пока ничего не запомнил.";

            return "Вот что я помню:\n\n" +
                   string.Join("\n", all.Select(x => $"• {x.Key} = {x.Value}"));
        }

        string key =
            lower.Contains("зовут") ? "имя" :
            lower.Contains("проект") ? "проект" :
            lower.Contains("видеокарта") ? "видеокарта" :
            lower.Contains("windows") ? "windows" :
            "";

        if (!string.IsNullOrEmpty(key))
        {
            var memory = _memory.Get(key);

            if (memory != null)
            {
                return key switch
                {
                    "имя" => $"Вас зовут {memory.Value}.",
                    "проект" => $"Ваш проект называется {memory.Value}.",
                    "видеокарта" => $"У вас видеокарта {memory.Value}.",
                    "windows" => $"Вы используете {memory.Value}.",
                    _ => memory.Value
                };
            }
        }

        var searchQuery = ExtractSearchQuery(lower);

        if (!string.IsNullOrEmpty(searchQuery))
        {
            var results = _memory.Search(searchQuery);

            if (results.Count > 0)
            {
                var best = results.First();
                return $"Из памяти: {best.Key} = {best.Value}";
            }
        }

        // Память не знает ответа → отдаём сообщение дальше, до AIHandler:
        // «что такое гравитация» должно доходить до LLM, а не получать
        // «Я пока не знаю ответ.».
        return null;
    }

    private static string ExtractSearchQuery(string lower)
    {
        var prefixes = new[]
        {
            "что такое ", "кто такой ", "кто такая ",
            "что значит ", "расскажи про ", "расскажи о "
        };

        foreach (var prefix in prefixes)
        {
            if (lower.Contains(prefix))
            {
                var idx = lower.IndexOf(prefix);
                return lower[(idx + prefix.Length)..].Trim();
            }
        }

        return "";
    }
}
