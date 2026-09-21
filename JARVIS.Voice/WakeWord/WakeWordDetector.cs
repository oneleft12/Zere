using JARVIS.Voice.Audio;
using JARVIS.Voice.Whisper;

namespace JARVIS.Voice.WakeWord;

/// <summary>
/// Детектор ключевого слова "Джарвис".
/// Непрерывно записывает короткие аудио-сегменты, распознаёт речь
/// и проверяет наличие ключевого слова в тексте.
/// </summary>
public class WakeWordDetector : IDisposable
{
    private readonly AudioRecorder _recorder = new();
    private readonly WhisperService _whisper = new();
    private readonly VoiceConfig _config;

    private readonly string[] _wakeWordVariants;

    public WakeWordDetector(VoiceConfig config)
    {
        _config = config;

        // Варианты ключевого слова (с учётом возможных ошибок распознавания)
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
    /// Записывает сегменты по 2.5 секунды и проверяет каждый на наличие wake word.
    /// </summary>
    /// <param name="ct">Токен отмены</param>
    /// <returns>Текст сегмента, в котором обнаружено ключевое слово</returns>
    public async Task<string> WaitForWakeWordAsync(CancellationToken ct = default)
    {
        const int segmentSeconds = 3; // Длина сегмента для сканирования

        while (!ct.IsCancellationRequested)
        {
            try
            {
                // Записываем короткий сегмент (3 секунды)
                var wavFile = await _recorder.RecordAsync(segmentSeconds);

                if (string.IsNullOrEmpty(wavFile) || !File.Exists(wavFile))
                    continue;

                // Проверяем размер файла — слишком маленький = тишина
                var fileInfo = new FileInfo(wavFile);
                if (fileInfo.Length < 2000)
                {
                    try { File.Delete(wavFile); } catch { }
                    continue;
                }

                // Распознаём речь
                var text = await _whisper.TranscribeAsync(wavFile);

                // Удаляем временный файл
                try { File.Delete(wavFile); } catch { }

                if (string.IsNullOrWhiteSpace(text))
                    continue;

                // Проверяем наличие ключевого слова
                var lowerText = text.ToLower().Trim();

                foreach (var variant in _wakeWordVariants)
                {
                    if (lowerText.Contains(variant))
                    {
                        Console.WriteLine($"🔔 Обнаружено ключевое слово: \"{text.Trim()}\"");
                        return text;
                    }
                }
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                // Логируем ошибку, но продолжаем работу
                Console.WriteLine($"⚠️ Ошибка при сканировании: {ex.Message}");
                await Task.Delay(500, ct);
            }
        }

        return string.Empty;
    }

    public void Dispose()
    {
        _recorder.Dispose();
        GC.SuppressFinalize(this);
    }
}
