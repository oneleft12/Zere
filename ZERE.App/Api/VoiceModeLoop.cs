using ZERE.Core;
using ZERE.Core.Context;
using ZERE.Core.Logging;
using ZERE.Voice;

namespace ZERE.App.Api;

/// <summary>
/// Фоновый цикл непрерывного голосового режима панели (GET/POST /api/voice/mode).
/// Зеркалит zere/voice/voice_mode.py (VoiceModeRunner): wake word → голосовая
/// команда → engine → озвучка ответа.
///
/// Семантика (эталон — Python-версия):
/// — wake word включён (Config.WakeWordEnabled) → спящий режим, ждём ключевое
///   слово, потом команду; выключен → слушаем команду сразу;
/// — «выход»/«стоп»/«exit» голосом → чистый выход из цикла (idle);
/// — пустое распознавание → пауза 300 мс (без горячего цикла);
/// — каждая обработанная реплика увеличивает turn в Status(): по нему панель
///   дописывает голосовой обмен в диалог чата (реплика идёт мимо /api/chat/stream);
/// — ошибка ProcessAsync/SpeakAsync не убивает цикл: пишем lastError
///   и слушаем дальше; неожиданный сбой → состояние error и выход;
/// — runtime.VoiceMode = true только на время ProcessAsync, чтобы
///   AIHandler отвечал коротко, а текстовый чат панели не «подрезался»;
/// — выход из цикла всегда гасит wake-детектор (DisableWakeWord).
/// </summary>
public sealed class VoiceModeLoop
{
    // Фазы цикла — значения поля state контракта VoiceModeState (openapi.yaml).
    public const string StateIdle = "idle";
    public const string StateSleeping = "sleeping";
    public const string StateListening = "listening";
    public const string StateProcessing = "processing";
    public const string StateSpeaking = "speaking";
    public const string StateError = "error";

    private static readonly string[] ExitWords = ["выход", "стоп", "exit"];

    // Пауза после пустого распознавания: микрофон молчит/ошибка — не крутим
    // горячий цикл (иначе 100% CPU на повторных попытках записи).
    private const int EmptyTranscriptPauseMs = 300;

    // Пауза при ложном возврате wake-детектора — тоже защита от горячего цикла.
    private const int WakeWordRetryDelayMs = 200;

    // Сколько ждём остановки цикла: запись с микрофона может быть длинной (VAD),
    // поэтому ожидание задачи ограничено, а не навсегда.
    private const int StopTimeoutMs = 2000;

    private readonly VoiceManager _voice;
    private readonly ZereEngine _engine;
    private readonly RuntimeContext? _runtime;
    private readonly LogService _log;
    private readonly object _lock = new();     // start/stop: управление циклом
    private readonly object _wakeLock = new(); // DisableWakeWord: stop и цикл гасят одновременно

    private CancellationTokenSource? _cts;
    private Task? _task;

    private volatile string _state = StateIdle;
    private volatile string _lastUtterance = "";
    private volatile string _lastAnswer = "";
    private volatile string? _lastError;

    // Счётчик обработанных голосовых реплик за жизнь процесса. Панель
    // опрашивает /api/voice/mode и по его росту дописывает пару
    // «услышано / ответ» в диалог чата: сама она о голосовой реплике иначе
    // не узнаёт (реплика идёт мимо /api/chat/stream). Не сбрасывается в Start():
    // иначе после повторного включения режима счётчик ушёл бы назад и чат
    // перестал видеть новые реплики. Пишет только поток цикла.
    private volatile int _turn;

    /// <param name="voice">Голосовой менеджер (STT/TTS, wake word).</param>
    /// <param name="engine">Тот же engine, что и в /api/chat/stream — общая история.</param>
    /// <param name="runtime">RuntimeContext: VoiceMode=true на время ProcessAsync.</param>
    /// <param name="log">Логгер панели (ошибки цикла не должны ронять приложение).</param>
    public VoiceModeLoop(VoiceManager voice, ZereEngine engine, RuntimeContext? runtime, LogService log)
    {
        _voice = voice;
        _engine = engine;
        _runtime = runtime;
        _log = log;
    }

    // ── Состояние (контракт VoiceModeState) ─────────────────────

    /// <summary>STT готов — режим вообще можно включить (иначе POST → 503).</summary>
    public bool Available => _voice.IsVoiceAvailable;

    /// <summary>Фоновый цикл жив: запущен через Start и ещё не завершился.</summary>
    public bool Enabled => _task is { IsCompleted: false };

    /// <summary>Текущее состояние цикла — тело ответа VoiceModeState.</summary>
    public object Status() => new
    {
        enabled = Enabled,
        state = _state,
        available = Available,
        wakeWordEnabled = _voice.Config.WakeWordEnabled,
        wakeWord = _voice.Config.WakeWord ?? string.Empty,
        // Движок триггера: onnx-kws (своя модель) или whisper (VAD+STT).
        wakeEngine = _voice.WakeEngineLabel,
        lastUtterance = _lastUtterance,
        lastAnswer = _lastAnswer,
        lastError = _lastError,
        // Растёт на 1 после каждой обработанной голосовой реплики.
        turn = _turn,
    };

    // ── Управление ──────────────────────────────────────────────

    /// <summary>
    /// Поднимает фоновый цикл. false — включить нельзя (STT недоступен).
    /// Повторный вызов при живом цикле идемпотентен (true).
    /// </summary>
    public bool Start()
    {
        lock (_lock)
        {
            if (_task is { IsCompleted: false })
                return true;

            if (!Available)
                return false;

            _cts?.Dispose();
            _cts = new CancellationTokenSource();
            var cts = _cts;

            _lastError = null;
            _state = StateSleeping;
            _task = Task.Run(() => RunAsync(cts));

            return true;
        }
    }

    /// <summary>
    /// Останавливает цикл: отмена + гасит текущую озвучку + ждёт выхода
    /// ограниченное время. Идемпотентен; после остановки состояние idle
    /// (если цикл не завершился ошибкой). lastUtterance/lastAnswer не сбрасываются.
    /// </summary>
    public void Stop(int timeoutMs = StopTimeoutMs)
    {
        Task? task;
        CancellationTokenSource? cts;

        lock (_lock)
        {
            task = _task;
            cts = _cts;
        }

        try
        {
            cts?.Cancel();
        }
        catch (ObjectDisposedException)
        {
            // CTS уже закрыт — отменять нечего
        }

        // Текущая озвучка не должна тянуть остановку (порт StopSpeaking).
        try
        {
            _voice.StopSpeaking();
        }
        catch (Exception)
        {
            // остановка не должна падать
        }

        if (task is not null)
        {
            try
            {
                task.Wait(TimeSpan.FromMilliseconds(timeoutMs));
            }
            catch (AggregateException)
            {
                // цикл завершился с исключением — состояние уже помечено
            }
        }

        if (task is null || task.IsCompleted)
        {
            // Цикл уже вышел (или его не было) — финализируем сами:
            // детектор мог остаться, если цикл не запускался.
            DisableWakeWord();

            if (_state != StateError)
                _state = StateIdle;

            try
            {
                cts?.Dispose();
            }
            catch (ObjectDisposedException)
            {
                // уже закрыт
            }
        }
    }

    // ── Цикл ────────────────────────────────────────────────────

    /// <summary>Основной цикл: wake word → команда → engine → озвучка.</summary>
    private async Task RunAsync(CancellationTokenSource cts)
    {
        var token = cts.Token;

        try
        {
            while (!token.IsCancellationRequested)
            {
                var text = await CaptureAsync(token).ConfigureAwait(false);

                if (token.IsCancellationRequested)
                    break;

                if (string.IsNullOrWhiteSpace(text))
                {
                    // Пустое распознавание → пауза и дальше (без горячего цикла).
                    await PauseAsync(EmptyTranscriptPauseMs, token).ConfigureAwait(false);
                    continue;
                }

                var command = text.Trim();

                if (Array.IndexOf(ExitWords, command.ToLowerInvariant()) >= 0)
                {
                    // Пользователь выключил режим голосом — чистый выход.
                    break;
                }

                _lastUtterance = command;
                _state = StateProcessing;

                string answer;

                try
                {
                    // Флаг только на время голосовой реплики: AIHandler отвечает
                    // коротко (этап 1, S5), текстовый чат панели не «подрезается».
                    if (_runtime is not null)
                        _runtime.VoiceMode = true;

                    answer = await _engine.ProcessAsync(command).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    // Ошибка engine цикл не убивает: пишем lastError и слушаем дальше.
                    _log.Error($"VoiceModeLoop.process: {ex.Message}");
                    _lastError = ex.Message;
                    _state = StateSleeping;
                    continue;
                }
                finally
                {
                    if (_runtime is not null)
                        _runtime.VoiceMode = false;
                }

                _lastAnswer = answer ?? string.Empty;
                // Реплика обработана — счётчик растёт до озвучки: чат должен
                // увидеть пару сразу, а не после того, как TTS проговорит ответ.
                _turn++;
                _state = StateSpeaking;

                try
                {
                    await _voice.SpeakAsync(_lastAnswer).ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    // Ошибка озвучки тоже не убивает цикл.
                    _log.Error($"VoiceModeLoop.speak: {ex.Message}");
                    _lastError = ex.Message;
                }

                _state = StateSleeping;
            }
        }
        catch (OperationCanceledException)
        {
            // Остановка цикла (отмена) — не ошибка: состояние станет idle.
        }
        catch (Exception ex)
        {
            // Неожиданный сбой цикла → состояние error и выход.
            _log.Error($"VoiceModeLoop: {ex.Message}");
            _lastError = ex.Message;
            _state = StateError;
        }
        finally
        {
            DisableWakeWord();

            // Остановили пользователем/«выходом» → idle; сбой уже помечен error.
            if (_state != StateError)
                _state = StateIdle;
        }
    }

    /// <summary>
    /// Одна попытка получить голосовую команду: wake word → команда
    /// или прямое прослушивание (без триггера).
    /// </summary>
    private async Task<string> CaptureAsync(CancellationToken token)
    {
        if (!_voice.Config.WakeWordEnabled)
        {
            _state = StateListening;
            return await _voice.ListenAsync().ConfigureAwait(false);
        }

        _state = StateSleeping;
        _voice.EnableWakeWord();

        while (!token.IsCancellationRequested)
        {
            bool detected;

            try
            {
                detected = await _voice.WaitForWakeWordAsync(token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return string.Empty; // отмена при остановке цикла
            }

            if (token.IsCancellationRequested)
                return string.Empty;

            if (!detected)
            {
                // Ложный возврат/перезапуск детектора — ждём дальше;
                // пауза нужна, чтобы не крутить горячий цикл.
                await PauseAsync(WakeWordRetryDelayMs, token).ConfigureAwait(false);
                continue;
            }

            _state = StateListening;
            return await _voice.ListenCommandAsync().ConfigureAwait(false);
        }

        return string.Empty;
    }

    // ── Помощники ───────────────────────────────────────────────

    /// <summary>Пауза, реагирующая на остановку цикла (как cancel.wait в Python).</summary>
    private static async Task PauseAsync(int delayMs, CancellationToken token)
    {
        try
        {
            await Task.Delay(delayMs, token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            // остановка — выходим из паузы сразу
        }
    }

    /// <summary>Гасит wake-детектор: детектор мог быть уже закрыт (stop и цикл).</summary>
    private void DisableWakeWord()
    {
        lock (_wakeLock)
        {
            try
            {
                _voice.DisableWakeWord();
            }
            catch (Exception)
            {
                // рекордер/детектор уже остановлены
            }
        }
    }
}
