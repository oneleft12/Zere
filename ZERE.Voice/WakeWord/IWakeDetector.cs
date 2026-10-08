using ZERE.Voice.Audio;

namespace ZERE.Voice.WakeWord;

/// <summary>
/// Общий контракт детектора слова-триггера: прежний VAD + STT и стриминговый
/// keyword spotting на ONNX-модели (docs/WAKE_WORD.md) взаимозаменяемы для
/// <see cref="VoiceManager"/>. Выбор движка — <see cref="WakeWordFactory"/>.
/// </summary>
public interface IWakeDetector : IDisposable
{
    /// <summary>Имя движка для статуса панели: "onnx-kws" или "whisper".</summary>
    string Engine { get; }

    /// <summary>Рекордер для записи команды после срабатывания.</summary>
    ContinuousAudioRecorder Recorder { get; }

    /// <summary>
    /// Ждёт произнесения ключевого слова. Возвращает найденное слово
    /// или "" при отмене.
    /// </summary>
    Task<string> WaitForWakeWordAsync(CancellationToken ct = default);
}
