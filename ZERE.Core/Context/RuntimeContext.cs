namespace ZERE.Core.Context;

/// <summary>
/// Флаги рантайма, общие для консоли, панели и AI-хендлера.
///
/// VoiceMode (анализ S5/этап 1 п.10): когда ответ будет произнесён вслух,
/// AIHandler добавляет в system-промпт требование короткого ответа и
/// ограничивает генерацию LlmMaxTokens — голос не должен печатать простыни.
/// </summary>
public sealed class RuntimeContext
{
    private volatile bool _voiceMode;

    /// <summary>true — ответ этой реплики будет озвучен голосом.</summary>
    public bool VoiceMode
    {
        get => _voiceMode;
        set => _voiceMode = value;
    }
}
