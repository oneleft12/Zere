using JARVIS.Memory.Database;

namespace JARVIS.Core.Handlers;

public class MemoryQueryHandler : IJarvisHandler
{
    private readonly MemoryRepository _memory = new();

    public bool CanHandle(string message)
    {
        var lower = message.ToLower().Trim();

        return lower.Contains("как меня зовут") ||
               lower.Contains("какой у меня проект") ||
               lower.Contains("что ты знаешь обо мне") ||
               lower.Contains("какая у меня видеокарта") ||
               lower.Contains("какая у меня windows");
    }

    public Task<string> HandleAsync(string message)
    {
        return Task.FromResult(Handle(message));
    }

    private string Handle(string message)
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

        var memory = _memory.Get(key);

        if (memory == null)
            return "Я пока не знаю ответ.";

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