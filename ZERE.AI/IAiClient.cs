namespace ZERE.AI;

/// <summary>
/// Общий контракт генерации текста: локальная Ollama или выбранный
/// провайдер ИИ (облачный ключ пользователя).
///
/// AIHandler зависит от этого интерфейса, поэтому смена провайдера из
/// панели работает на лету, без перезапуска ZERE
/// (паритет с Python-редакцией, zere/ai/ai_service.py).
/// </summary>
public interface IAiClient
{
    Task<string> GenerateAsync(
        string prompt,
        string? systemPrompt = null,
        float? temperature = null,
        int? maxTokens = null);

    /// <summary>Прогрев активного локального провайдера (ошибки не критичны).</summary>
    Task WarmupAsync();
}
