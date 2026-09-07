using JARVIS.AI;
using JARVIS.Core.Intent;
using JARVIS.Tools.Applications;
using JARVIS.Memory.Database;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly OllamaClient _ai = new();
    private readonly ApplicationLauncher _launcher = new();
    private readonly IntentRouter _router = new();

    private readonly ConversationRepository _conversations = new();
    private readonly MemoryRepository _memory = new();

    public async Task<string> ProcessAsync(string message)
    {
        var lower = message.ToLower().Trim();

        // ==========================================
        // ПАМЯТЬ SQLITE
        // ==========================================

        // Запомнить информацию
        if (lower.StartsWith("запомни"))
        {
            var text = message.Trim();

            // Убираем "запомни"
            text = text.Substring("запомни".Length).Trim();

            // Убираем необязательные слова
            if (text.StartsWith("что ", StringComparison.OrdinalIgnoreCase))
                text = text.Substring(4).Trim();

            if (text.StartsWith("мое ", StringComparison.OrdinalIgnoreCase))
                text = text.Substring(4).Trim();

            if (text.StartsWith("мой ", StringComparison.OrdinalIgnoreCase))
                text = text.Substring(4).Trim();

            if (text.StartsWith("моя ", StringComparison.OrdinalIgnoreCase))
                text = text.Substring(4).Trim();

            string key;
            string value;

            if (text.Contains("="))
            {
                var parts = text.Split("=", 2);
                key = parts[0].Trim().ToLowerInvariant();
                value = parts[1].Trim();
            }
            else
            {
                var words = text.Split(' ', StringSplitOptions.RemoveEmptyEntries);

                if (words.Length < 2)
                    return "Напиши, что нужно запомнить. Например: запомни имя Dan";

                key = words[0].Trim().ToLowerInvariant();
                value = string.Join(" ", words.Skip(1));
            }

            _memory.Remember(key, value);

            return $"Запомнил: {key} = {value}";
        }

        // Показать всю память
        if (lower.StartsWith("покажи память"))
        {
            var memories = _memory.GetAll();

            if (memories.Count == 0)
                return "Я пока ничего не запомнил.";

            return "Вот что я помню:\n\n" +
                   string.Join(
                       "\n",
                       memories.Select(m => $"• {m.Key} = {m.Value}")
                   );
        }

        // Что ты знаешь обо мне
        if (lower.StartsWith("что ты знаешь обо мне"))
        {
            var memories = _memory.GetAll();

            if (memories.Count == 0)
                return "Я пока ничего не запомнил.";

            return "Вот что я знаю о тебе:\n\n" +
                   string.Join(
                       "\n",
                       memories.Select(m => $"• {m.Key} = {m.Value}")
                   );
        }

        // Забыть запись
        if (lower.StartsWith("забудь "))
        {
            var key = message.Substring("забудь ".Length).Trim();

            return _memory.Forget(key)
                ? $"Забыл: {key}"
                : $"Не нашёл в памяти: {key}";
        }

        // Показать историю
        if (lower.StartsWith("покажи историю"))
        {
            var history = _conversations.GetLast(10);

            if (history.Count == 0)
                return "История пока пуста.";

            return string.Join(
                "\n\n",
                history.Select(h =>
                    $"Вы: {h.UserMessage}\nJARVIS: {h.JarvisResponse}")
            );
        }

        // ==========================================
        // ИНДЕКС ПРИЛОЖЕНИЙ
        // ==========================================

        if (lower == "обнови индекс")
        {
            _launcher.RebuildIndex();
            return "Индекс приложений успешно пересоздан.";
        }

        if (lower == "сколько приложений")
        {
            return $"В индексе {_launcher.GetInstalledApplications().Count} приложений.";
        }

        if (lower.StartsWith("найди "))
        {
            var query = lower.Replace("найди ", "");

            var apps = _launcher.GetInstalledApplications()
                .Values
                .Where(a => a.Name.Contains(query, StringComparison.OrdinalIgnoreCase))
                .Take(10)
                .Select(a => $"{a.Name} ({a.Source})");

            return string.Join("\n", apps);
        }

        // ==========================================
        // ЗАПУСК ПРИЛОЖЕНИЙ
        // ==========================================

        var intent = _router.Parse(message);

        string answer;

        switch (intent.Type)
        {
            case IntentType.OpenApplication:

                answer = _launcher.Launch(intent.Value)
                    ? $"Открываю {intent.Value}."
                    : $"Не удалось найти приложение «{intent.Value}».";
                break;

            default:

                answer = await _ai.GenerateAsync(message);
                break;
        }

        // ==========================================
        // СОХРАНЯЕМ ИСТОРИЮ ДИАЛОГА
        // ==========================================

        _conversations.Save(message, answer);

        return answer;
    }
}