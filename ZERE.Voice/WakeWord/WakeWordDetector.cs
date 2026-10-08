using ZERE.Voice.Audio;
using ZERE.Voice.Whisper;
using System.Text.RegularExpressions;

namespace ZERE.Voice.WakeWord;

/// <summary>
/// Детектор ключевого слова "Зере".
/// Использует непрерывную запись с круговым буфером и энергетический VAD.
/// Отправляет аудио в Whisper ТОЛЬКО при обнаружении речи — без лишних вызовов.
/// Сопоставление нечёткое (Levenshtein) — ловит «зера», «зерэ», «зире».
/// </summary>
public class WakeWordDetector : IWakeDetector
{
    private readonly ContinuousAudioRecorder _recorder = new();
    private readonly WhisperService _whisper;
    private readonly bool _ownsWhisper;
    private readonly VoiceConfig _config;

    // Точные варианты (проверка подстрокой)
    private readonly string[] _wakeWordVariants;

    // Ядра для нечёткого сравнения (расстояние Левенштейна).
    // Имя короткое, поэтому «зере/зера/зире» перекрывают искажения Whisper,
    // а порог по длине слова (см. IsWakeWord) держит ложные срабатывания
    // низкими: слово короче 4 букв в сравнение не попадает.
    private static readonly string[] FuzzyCores =
    {
        "зере", "зера", "зерэ", "зире", "zere"
    };

    // Настройки
    private const float PreSpeechBufferSeconds = 1.5f; // Буфер до начала речи
    private const float MinSpeechSeconds = 0.5f;       // Минимальная длительность речи
    private const float MaxSegmentSeconds = 9f;        // Макс. окно извлечения (буфер 10 сек)
    private const float ScanIntervalMs = 400;          // Интервал проверки энергии

    // Таймаут транскрибации wake-сегмента (короткий, ≤9 с аудио): 15 с
    // достаточно даже на слабом CPU, зависание не блокирует петлю.
    private const int WakeTranscribeTimeoutSeconds = 15;

    /// <param name="config">Конфигурация голоса.</param>
    /// <param name="whisper">
    /// Общий сервис STT (анализ S3): одна модель на процесс вместо второй
    /// копии в каждом новом детекторе. Если не передан — создаётся свой
    /// (тогда детектор владеет им и освобождает в Dispose).
    /// </param>
    public WakeWordDetector(VoiceConfig config, WhisperService? whisper = null)
    {
        _config = config;
        _whisper = whisper ?? new WhisperService();
        _ownsWhisper = whisper == null;

        _wakeWordVariants = new[]
        {
            config.WakeWord.ToLower(),
            "зере",
            "зера",
            "зерэ",
            "зире",
            "zere"
        };
    }

    /// <summary>Имя движка для статуса панели (прежний VAD + STT).</summary>
    public string Engine => "whisper";

    /// <summary>
    /// Ожидает произнесения ключевого слова.
    /// Непрерывно записывает аудио, определяет речь по энергии,
    /// и отправляет в Whisper только сегменты с речью.
    /// </summary>
    public async Task<string> WaitForWakeWordAsync(CancellationToken ct = default)
    {
        // Запускаем непрерывную запись (если уже идёт — не перезапускаем,
        // чтобы не терять калибровку VAD на каждом цикле)
        _recorder.StartContinuousRecording(bufferSeconds: 10);

        var completed = false;

        try
        {
            while (!ct.IsCancellationRequested)
            {
                // Ждём появления речи
                while (!_recorder.IsSpeechDetected && !ct.IsCancellationRequested)
                {
                    await Task.Delay((int)ScanIntervalMs, ct);
                }

                if (ct.IsCancellationRequested) break;

                // Речь обнаружена — ждём окончания (тишина после речи)
                var speechStartTime = DateTime.Now;
                var lastSpeechTime = DateTime.Now;

                while (!ct.IsCancellationRequested)
                {
                    await Task.Delay(200, ct);

                    if (_recorder.IsSpeechDetected)
                    {
                        lastSpeechTime = DateTime.Now;
                    }

                    var silenceDuration = (DateTime.Now - lastSpeechTime).TotalMilliseconds;
                    var speechDuration = (DateTime.Now - speechStartTime).TotalSeconds;

                    // Пауза окончания речи — из конфига (было жёсткие 1200 мс,
                    // анализ S4: каждый цикл платил 1.2 с сверху).
                    if (silenceDuration > _config.WakeSilenceMs && speechDuration >= MinSpeechSeconds)
                        break;

                    // Слишком длинная речь (>8 сек) — берём всё что есть в буфере
                    if (speechDuration > 8)
                        break;
                }

                if (ct.IsCancellationRequested) break;

                // Извлекаем сегмент: буфер до речи + вся речь + хвост.
                // ВАЖНО: окно = вся речь + буфер, ограничено только размером
                // кольцевого буфера (9 сек) — «Джарвис» в начале длинной речи
                // больше не обрезается.
                var totalSeconds = (float)(DateTime.Now - speechStartTime).TotalSeconds
                                   + PreSpeechBufferSeconds;
                totalSeconds = Math.Min(totalSeconds, MaxSegmentSeconds);

                // Сохраняем во временный файл
                var wavFile = _recorder.SaveRecentAudio(totalSeconds);

                if (string.IsNullOrEmpty(wavFile) || !File.Exists(wavFile))
                    continue;

                // Проверяем размер — слишком маленький = проблема
                var fileInfo = new FileInfo(wavFile);
                if (fileInfo.Length < 2000)
                {
                    TryDelete(wavFile);
                    continue;
                }

                // Распознаём речь (wake-сегмент короткий — таймаут 15 с)
                var text = await _whisper.TranscribeAsync(
                    wavFile, timeoutSeconds: WakeTranscribeTimeoutSeconds);

                // Удаляем временный файл
                TryDelete(wavFile);

                if (string.IsNullOrWhiteSpace(text))
                    continue;

                // Проверяем наличие ключевого слова (сначала точно, потом нечётко)
                if (IsWakeWord(text))
                {
                    Console.WriteLine($"🔔 Обнаружено: \"{text.Trim()}\"");
                    completed = true;
                    return text;
                }

                // Отладочный вывод: что реально распознал Whisper
                Console.WriteLine($"💤 Распознано: \"{text.Trim()}\" (не ключевое слово)");
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            Console.WriteLine($"⚠️ Ошибка детектора: {ex.Message}");
        }
        finally
        {
            // Останавливаем запись только если не нашли wake word:
            // при успехе рекордер продолжает работать для записи команды
            // (и не нужна повторная калибровка VAD на следующем цикле)
            if (!completed)
                _recorder.StopContinuousRecording();
        }

        return string.Empty;
    }

    /// <summary>
    /// Получает ссылку на рекордер для записи команды после wake word.
    /// </summary>
    public ContinuousAudioRecorder Recorder => _recorder;

    /// <summary>
    /// Проверяет текст на ключевое слово: точное совпадение подстроки,
    /// затем нечёткое сравнение по словам (расстояние Левенштейна ≤ 1–2).
    /// </summary>
    private bool IsWakeWord(string text)
    {
        var norm = text.ToLowerInvariant().Replace('ё', 'е');

        // 1) Точная проверка подстрокой
        foreach (var variant in _wakeWordVariants)
        {
            if (norm.Contains(variant))
                return true;
        }

        // 2) Нечёткое сравнение по словам (ловит «зера», «зерэ», «зире»)
        var words = Regex.Split(norm, @"[^\p{L}]+");

        foreach (var word in words)
        {
            if (word.Length < 4 || word.Length > 12)
                continue;

            foreach (var core in FuzzyCores)
            {
                if (Math.Abs(word.Length - core.Length) > 2)
                    continue;

                // Порог зависит от длины: короткие слова — строже (меньше ложных срабатываний)
                var maxDistance = word.Length >= 6 ? 2 : 1;

                if (Levenshtein(word, core) <= maxDistance)
                    return true;
            }
        }

        return false;
    }

    /// <summary>Расстояние Левенштейна (оптимизированная матрица).</summary>
    private static int Levenshtein(string a, string b)
    {
        var prev = new int[b.Length + 1];
        var curr = new int[b.Length + 1];

        for (int j = 0; j <= b.Length; j++)
            prev[j] = j;

        for (int i = 1; i <= a.Length; i++)
        {
            curr[0] = i;

            for (int j = 1; j <= b.Length; j++)
            {
                var cost = a[i - 1] == b[j - 1] ? 0 : 1;
                curr[j] = Math.Min(
                    Math.Min(curr[j - 1] + 1, prev[j] + 1),
                    prev[j - 1] + cost);
            }

            (prev, curr) = (curr, prev);
        }

        return prev[b.Length];
    }

    private static void TryDelete(string path)
    {
        try { File.Delete(path); } catch { }
    }

    public void Dispose()
    {
        _recorder.Dispose();

        // Общий Whisper (передан снаружи) принадлежит VoiceManager —
        // освобождаем только собственный экземпляр (анализ S3/F3).
        if (_ownsWhisper)
            _whisper.Dispose();

        GC.SuppressFinalize(this);
    }
}
