namespace ZERE.Voice;

/// <summary>
/// Контракт STT-движка (распознавания речи). Реализации:
/// <see cref="Sherpa.GigaAmService"/> — GigaAM-v3 (основной) и
/// <see cref="Whisper.WhisperService"/> — Whisper (откат),
/// роутинг — VoiceManager.ConfigureStt (паритет роутинга TTS pocket→silero).
/// </summary>
public interface ISttService : IDisposable
{
    /// <summary>Человекочитаемое имя текущей модели для логов и [Perf]-метрик.</summary>
    string CurrentModel { get; }

    /// <summary>Модель готова к распознаванию (файлы модели на месте).</summary>
    bool IsInstalled();

    /// <summary>
    /// Предзагрузка модели в память при старте; для GigaAM при отсутствии
    /// модели выполняется разовое скачивание. Сбои не критичны (возврат false).
    /// </summary>
    bool Preload();

    /// <summary>
    /// Распознаёт WAV-файл. timeoutSeconds — защита от зависания: по истечении
    /// возвращается пустой результат, фоновая задача доработает сама.
    /// </summary>
    Task<string> TranscribeAsync(string wavFile, int timeoutSeconds = 30);
}
