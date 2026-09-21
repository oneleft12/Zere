using JARVIS.Voice.Audio;
using JARVIS.Voice.Whisper;

namespace JARVIS.Voice.WakeWord;

/// <summary>
/// Детектор ключевого слова "Джарвис".
/// Использует непрерывную запись с круговым буфером и энергетический VAD.
/// Отправляет аудио в Whisper ТОЛЬКО при обнаружении речи — без лишних вызовов.
/// </summary>
public class WakeWordDetector : IDisposable
{
    private readonly ContinuousAudioRecorder _recorder = new();
    private readonly WhisperService _whisper = new();
    private readonly VoiceConfig _config;

    private readonly string[] _wakeWordVariants;

    // Настройки
    private const float ListenChunkSeconds = 3f;    // Длина сегмента для анализа
    private const float PreSpeechBufferSeconds = 1f; // Буфер до начала речи
    private const float MinSpeechSeconds = 0.5f;     // Минимальная длительность речи
    private const float ScanIntervalMs = 500;        // Интервал проверки энергии

    public WakeWordDetector(VoiceConfig config)
    {
        _config = config;

        _wakeWordVariants = new[]
        {
            config.WakeWord.ToLower(),
            "джарвис",
            "джэрвис",
            "джервис",
            "джервис",
            "jarvis"
        };
    }

    /// <summary>
    /// Ожидает произнесения ключевого слова.
    /// Непрерывно записывает аудио, определяет речь по энергии,
    /// и отправляет в Whisper только сегменты с речью.
    /// </summary>
    public async Task<string> WaitForWakeWordAsync(CancellationToken ct = default)
    {
        // Запускаем непрерывную запись (10-секундный буфер)
        _recorder.StartContinuousRecording(bufferSeconds: 10);

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

                // Речь обнаружена — ждём окончания (тишина 1.5 сек)
                var speechStartTime = DateTime.Now;
                var lastSpeechTime = DateTime.Now;

                while (!ct.IsCancellationRequested)
                {
                    await Task.Delay(200, ct);

                    if (_recorder.IsSpeechDetected)
                    {
                        lastSpeechTime = DateTime.Now;
                    }

                    // Тишина > 1.5 сек после речи
                    var silenceDuration = (DateTime.Now - lastSpeechTime).TotalMilliseconds;
                    var speechDuration = (DateTime.Now - speechStartTime).TotalSeconds;

                    if (silenceDuration > 1500 && speechDuration >= MinSpeechSeconds)
                        break;

                    // Слишком длинная речь (>8 сек) — обрезаем
                    if (speechDuration > 8)
                        break;
                }

                if (ct.IsCancellationRequested) break;

                // Извлекаем сегмент: буфер до речи + вся речь + хвост
                var totalSeconds = (float)(DateTime.Now - speechStartTime).TotalSeconds
                                   + PreSpeechBufferSeconds + 0.5f;
                totalSeconds = Math.Min(totalSeconds, ListenChunkSeconds + 2f);

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

                // Распознаём речь
                var text = await _whisper.TranscribeAsync(wavFile);

                // Удаляем временный файл
                TryDelete(wavFile);

                if (string.IsNullOrWhiteSpace(text))
                    continue;

                // Проверяем наличие ключевого слова
                var lowerText = text.ToLower().Trim();

                foreach (var variant in _wakeWordVariants)
                {
                    if (lowerText.Contains(variant))
                    {
                        Console.WriteLine($"🔔 Обнаружено: \"{text.Trim()}\"");
                        return text;
                    }
                }
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            Console.WriteLine($"⚠️ Ошибка детектора: {ex.Message}");
        }
        finally
        {
            _recorder.StopContinuousRecording();
        }

        return string.Empty;
    }

    /// <summary>
    /// Получает ссылку на рекордер для записи команды после wake word.
    /// </summary>
    public ContinuousAudioRecorder Recorder => _recorder;

    private static void TryDelete(string path)
    {
        try { File.Delete(path); } catch { }
    }

    public void Dispose()
    {
        _recorder.Dispose();
        GC.SuppressFinalize(this);
    }
}
