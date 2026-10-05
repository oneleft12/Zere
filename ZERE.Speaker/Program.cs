using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using ZERE.Voice.Audio;

namespace ZERE.Speaker;

/// <summary>
/// Хелпер озвучки: DSP-обработка WAV (<see cref="AudioProcessor"/>) и вывод
/// звука (<see cref="AudioPlayer"/> → NAudio/WASAPI) вынесены в отдельный
/// C#-процесс, чтобы Python-редакция отдавала озвучку коду на C#.
///
/// Режимы:
/// <list type="bullet">
/// <item><c>host</c> — долгоживущий процесс: команды строками JSON (по одной
/// на строку) на stdin, ответы — строки JSON на stdout. Поднимается один раз
/// на сессию: старт процесса и JIT не попадают в задержку каждой фразы.</item>
/// <item><c>speak &lt;wav&gt; [volume]</c> — разовая озвучка (отладка).</item>
/// </list>
///
/// Протокол (v1):
/// <code>
/// → {"cmd":"speak","wav":"…","volume":0.5,"process":true,"rate":44100,"dry":false}
/// ← {"event":"done","file":"…","processMs":12,"playMs":410,"played":true}
/// → {"cmd":"stop"}      ← {"event":"stopped"}
/// → {"cmd":"ping"}      ← {"event":"pong","version":"1"}
/// → {"cmd":"quit"}      ← {"event":"bye"}
/// </code>
///
/// Вывод: JSON-ответы идут в stdout, **все** диагностические сообщения — в
/// stderr (Console перенаправляется), иначе строки вида «[AudioPlayer] …»
/// ломали бы протокол.
/// </summary>
internal static class Program
{
    /// <summary>Версия протокола: Python сверяет её при старте.</summary>
    private const string ProtocolVersion = "1";

    private static readonly object OutLock = new();
    private static TextWriter _replies = Console.Out;

    private static AudioPlayer? _current;
    private static Task? _playTask;

    private static int Main(string[] args)
    {
        if (args.Length == 0 || args[0] == "host")
            return RunHost();

        if (args[0] == "speak")
            return RunSpeakOnce(args);

        Console.Error.WriteLine(
            "Использование: ZERE.Speaker host | ZERE.Speaker speak <wav> [volume]");
        return 2;
    }

    // ─── Режим host: JSON-строки на stdin ───────────────────────

    private static int RunHost()
    {
        // Диагностика AudioPlayer/AudioProcessor уходит в stderr, протокол
        // остаётся чистым: в stdout пишем только JSON-ответы.
        _replies = Console.Out;
        Console.SetOut(Console.Error);

        using var input = new StreamReader(Console.OpenStandardInput(), Encoding.UTF8);

        Reply(new JsonObject { ["event"] = "ready", ["version"] = ProtocolVersion });

        string? line;
        while ((line = input.ReadLine()) != null)
        {
            line = line.Trim();
            if (line.Length == 0)
                continue;

            JsonObject? request;
            try
            {
                request = JsonNode.Parse(line) as JsonObject;
            }
            catch (JsonException ex)
            {
                Reply(new JsonObject { ["event"] = "error", ["message"] = ex.Message });
                continue;
            }

            if (request is null)
            {
                Reply(new JsonObject { ["event"] = "error", ["message"] = "не JSON-объект" });
                continue;
            }

            var command = request["cmd"]?.GetValue<string>() ?? "";

            switch (command)
            {
                case "speak":
                    HandleSpeak(request);
                    break;
                case "stop":
                    _current?.Stop();
                    Reply(new JsonObject { ["event"] = "stopped" });
                    break;
                case "ping":
                    Reply(new JsonObject { ["event"] = "pong", ["version"] = ProtocolVersion });
                    break;
                case "quit":
                    _current?.Stop();
                    Reply(new JsonObject { ["event"] = "bye" });
                    return 0;
                default:
                    Reply(new JsonObject
                    {
                        ["event"] = "error",
                        ["message"] = $"неизвестная команда: «{command}»"
                    });
                    break;
            }
        }

        _current?.Stop();
        return 0;
    }

    private static void HandleSpeak(JsonObject request)
    {
        var wav = request["wav"]?.GetValue<string>() ?? "";
        var volume = (float)(request["volume"]?.GetValue<double>() ?? 1.0);
        var process = request["process"]?.GetValue<bool>() ?? true;
        var rate = request["rate"]?.GetValue<int>() ?? AudioProcessor.DefaultSampleRate;
        var dry = request["dry"]?.GetValue<bool>() ?? false;

        var file = wav;
        long processMs = 0;

        if (process && wav.Length > 0)
        {
            var stopwatch = Stopwatch.StartNew();
            file = AudioProcessor.Process(wav, rate);   // сбой → исходный файл
            processMs = stopwatch.ElapsedMilliseconds;
        }

        if (dry || file.Length == 0 || !File.Exists(file))
        {
            Reply(new JsonObject
            {
                ["event"] = "done",
                ["file"] = file,
                ["processMs"] = processMs,
                ["played"] = false,
                ["reason"] = dry ? "dry" : "нет файла"
            });
            return;
        }

        // Предыдущая фраза ещё звучит — не наслаиваем два потока.
        if (_playTask is { IsCompleted: false })
            _playTask.Wait();

        var player = new AudioPlayer();
        _current = player;

        _playTask = Task.Run(async () =>
        {
            var stopwatch = Stopwatch.StartNew();
            await player.PlayAsync(file, volume);
            var playMs = stopwatch.ElapsedMilliseconds;

            // Обработанный файл — временный артефакт (в C#-редакции его так же
            // удаляет VoiceManager после озвучки). В dry-режиме файл остаётся
            // вызывающему: он для проверки DSP без вывода звука.
            if (file != wav)
                TryDelete(file);

            Reply(new JsonObject
            {
                ["event"] = "done",
                ["file"] = file,
                ["processMs"] = processMs,
                ["playMs"] = playMs,
                ["played"] = true
            });
        });
    }

    /// <summary>Удаляет временный файл, молча глотая ошибки файловой системы.</summary>
    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (IOException)
        {
            // Файл занят/уже удалён — мусор не критичен.
        }
        catch (UnauthorizedAccessException)
        {
            // Нет прав на удаление — оставляем файл.
        }
    }

    // ─── Режим speak: разовая озвучка ───────────────────────────

    private static int RunSpeakOnce(string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine("speak: не указан WAV-файл");
            return 2;
        }

        var wav = args[1];
        var volume = args.Length > 2 && float.TryParse(args[2], out var parsed) ? parsed : 1.0f;

        var processed = AudioProcessor.Process(wav, AudioProcessor.DefaultSampleRate);

        using var player = new AudioPlayer();
        player.PlayAsync(processed, volume).GetAwaiter().GetResult();

        return 0;
    }

    private static void Reply(JsonObject payload)
    {
        lock (OutLock)
        {
            _replies.WriteLine(payload.ToJsonString());
            _replies.Flush();
        }
    }
}
