using JARVIS.AI;
using JARVIS.Core.Intent;
using JARVIS.Tools.Applications;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly OllamaClient _ai = new();
    private readonly ApplicationLauncher _launcher = new();
    private readonly IntentRouter _router = new();

    public async Task<string> ProcessAsync(string message)
    {
        var lower = message.ToLower().Trim();

        // Новая команда
        if (lower == "покажи приложения")
        {
            var apps = _launcher.GetInstalledApplications();

            return "Найдено приложений: " + apps.Count +
                   "\n\n" +
                   string.Join("\n", apps.Take(40));
        }
            if (lower == "обнови индекс")
        {
    _launcher.RebuildIndex();
            return "Индекс приложений успешно обновлён.";
        }
                var intent = _router.Parse(message);

            switch (intent.Type)
        {
            case IntentType.OpenApplication:

                var success = _launcher.Launch(intent.Value);

                return success
                    ? $"Открываю {intent.Value}."
                    : $"Не удалось найти приложение «{intent.Value}».";

            default:
                return await _ai.GenerateAsync(message);
        }
    }
}