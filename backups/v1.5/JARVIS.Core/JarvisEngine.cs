using JARVIS.AI;
using JARVIS.Core.Intent;
using JARVIS.Tools.Applications;
using JARVIS.Memory.Database;
using JARVIS.Memory.Services;
using JARVIS.Tools.Windows;
using JARVIS.Tools.System;
using JARVIS.Tools.FileManager;
using JARVIS.Voice.Audio;
using JARVIS.Core.Handlers;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly MemoryHandler _memoryHandler = new();
    private readonly VoiceManager _voice = new();
    private readonly FileCommandRouter _fileRouter = new();
    private readonly FileManagerService _fileManager = new();

    private string? _pendingDeleteFile;
    private readonly OllamaClient _ai = new();
    private readonly ApplicationLauncher _launcher = new();
    private readonly AudioController _audio = new();
    private readonly FileController _files = new();
    private readonly SystemInfoService _system = new();
    private readonly PowerController _power = new();
    private readonly WindowsCommandRouter _windows = new();
    private readonly IntentRouter _router = new();
    private readonly ScreenCaptureService _screen = new();
    private readonly SafeActionManager _safeActions = new();
    private readonly ConversationRepository _conversations = new();
    private readonly MemoryRepository _memory = new();
    private readonly MemoryExtractor _extractor = new();

    public async Task<string> ProcessAsync(string message)
    {
        var lower = message.ToLower().Trim();

        // ==========================================
        // FILE MANAGER
        // ==========================================

var fileCommand = _fileRouter.Parse(message);

switch (fileCommand.Type)
{
    case FileCommandType.CreateFolder:
    {
        var path = _fileManager.CreateFolder(fileCommand.Value);
        return $"Папка создана:\n{path}";
    }

    case FileCommandType.CreateFile:
    {
        var path = _fileManager.CreateFile(fileCommand.Value);
        return $"Файл создан:\n{path}";
    }

    case FileCommandType.ReadFile:
    {
        return _fileManager.ReadFile(fileCommand.Value);
    }

    case FileCommandType.WriteFile:
    {
        var path = _fileManager.WriteFile(fileCommand.Value);
        return $"Записал текст в файл:\n{path}";
    }

    case FileCommandType.SearchFile:
    {
        var files = _fileManager.SearchFile(fileCommand.Value);

        if (files.Count == 0)
            return "Файлы не найдены.";

        return string.Join("\n", files);
    }

    case FileCommandType.SearchFolder:
    {
        var folders = _fileManager.SearchFolder(fileCommand.Value);

        if (folders.Count == 0)
            return "Папки не найдены.";

        return string.Join("\n", folders);
    }

    case FileCommandType.DeleteFile:
    {
        var files = _fileManager.SearchFile(fileCommand.Value);

        if (files.Count == 0)
            return "Файл не найден.";

        _pendingDeleteFile = files.First();

        return $"Удалить файл?\n{_pendingDeleteFile}\n\nНапишите «да» или «нет».";
    }
}
        
// ==========================================
// SAFE ACTION ENGINE
// ==========================================

if (_safeActions.HasPending())
{
    if (lower == "да")
    {
        switch (_safeActions.Pending)
        {
            case PendingAction.Shutdown:
                _power.Shutdown();
                break;

            case PendingAction.Restart:
                _power.Restart();
                break;

            case PendingAction.Sleep:
                _power.Sleep();
                break;
        }

        _safeActions.Clear();
        return "Выполняю команду.";
    }

    if (lower == "нет")
    {
        _safeActions.Clear();
        return "Команда отменена.";
    }
}

// ==========================================
// SAFE DELETE
// ==========================================

if (_pendingDeleteFile != null)
{
    if (lower == "да")
    {
        var ok = _fileManager.DeleteFile(_pendingDeleteFile);

        _pendingDeleteFile = null;

        return ok
            ? "Файл удалён."
            : "Не удалось удалить файл.";
    }

    if (lower == "нет")
    {
        _pendingDeleteFile = null;

        return "Удаление отменено.";
    }
}

        // ==========================================
        // АВТОМАТИЧЕСКАЯ ПАМЯТЬ
        // ==========================================

      var facts = _extractor.Extract(message);

         foreach (var fact in facts)
      {
          _memory.Remember(fact.Key, fact.Value, fact.Category);
      }

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

    var grouped = memories
        .GroupBy(m => m.Category)
        .OrderBy(g => g.Key);

    var lines = new List<string>();

    foreach (var group in grouped)
       {
        lines.Add($"[{group.Key}]");

        foreach (var memory in group)
            lines.Add($"• {memory.Key} = {memory.Value}");

        lines.Add("");
        }
          
    return string.Join("\n", lines);
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
    if (lower == "очисти память")
        {
           _memory.Clear();

           return "Память полностью очищена.";
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
// WINDOWS BRAIN
// ==========================================

switch (_windows.Parse(message))
{
    // ===== Громкость =====

    case WindowsCommandType.VolumeUp:
        _audio.VolumeUp();
        return "Увеличиваю громкость.";

    case WindowsCommandType.VolumeDown:
        _audio.VolumeDown();
        return "Уменьшаю громкость.";

    case WindowsCommandType.VolumeMute:
        _audio.ToggleMute();
        return "Звук выключен.";

    case WindowsCommandType.VolumeUnmute:
        _audio.ToggleMute();
        return "Звук включён.";

    // ===== Папки =====

    case WindowsCommandType.OpenDownloads:
        _files.OpenDownloads();
        return "Открываю папку Загрузки.";

    case WindowsCommandType.OpenDesktop:
        _files.OpenDesktop();
        return "Открываю Рабочий стол.";

    case WindowsCommandType.OpenDocuments:
        _files.OpenDocuments();
        return "Открываю Документы.";

    // ===== Информация о системе =====

    case WindowsCommandType.CpuInfo:
        return $"Процессор: {_system.GetCpu()}";

    case WindowsCommandType.GpuInfo:
        return $"Видеокарта: {_system.GetGpu()}";

    case WindowsCommandType.RamInfo:
        return $"Оперативная память: {_system.GetRam()}";

    case WindowsCommandType.WindowsInfo:
        return $"Windows: {_system.GetWindowsVersion()}";

    case WindowsCommandType.RunningProcesses:
        return "Запущенные процессы:\n\n" +
               string.Join("\n", _system.GetRunningProcesses());

    // ===== Скриншот =====

    case WindowsCommandType.Screenshot:
    {
        var path = _screen.Capture();
        return $"Скриншот сохранён:\n{path}";
    }

    // ===== Опасные действия =====

    case WindowsCommandType.Shutdown:
        _safeActions.Request(PendingAction.Shutdown);
        return "Вы уверены, что хотите выключить компьютер? Напишите «да» или «нет».";

    case WindowsCommandType.Restart:
        _safeActions.Request(PendingAction.Restart);
        return "Вы уверены, что хотите перезагрузить компьютер? Напишите «да» или «нет».";

    case WindowsCommandType.Sleep:
        _safeActions.Request(PendingAction.Sleep);
        return "Перевести компьютер в сон? Напишите «да» или «нет».";

    case WindowsCommandType.Lock:
        _power.Lock();
        return "Компьютер заблокирован.";
}
       // ========= VOICE ENGINE =========
if (lower == "проверь голос")
{
    return _voice.IsInstalled()
        ? "Whisper установлен и готов."
        : "Whisper не найден. Проверь папку models/whisper.";
        }

        if (lower == "режим голоса")
{
    if (!_voice.IsInstalled())
        return "Whisper не установлен.";

    Console.WriteLine();
    Console.WriteLine("🎤 Голосовой режим активирован.");
    Console.WriteLine("Говорите...");

    var recognized = await _voice.ListenAsync();

    if (string.IsNullOrWhiteSpace(recognized))
        return "Я ничего не услышал.";

    Console.WriteLine($"Вы сказали: {recognized}");

    return await ProcessAsync(recognized);
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