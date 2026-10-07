using ZERE.AI;
using ZERE.Core.AI;
using ZERE.Core.Configuration;
using ZERE.Core.Context;
using ZERE.Core.Plugins;

namespace ZERE.Core.Handlers;

public class AIHandler : IZereHandler
{
    private readonly IAiClient _ai;
    private readonly ContextBuilder _context;
    private readonly PluginManager _pluginManager;
    private readonly RuntimeContext? _runtime;
    private readonly ZereConfig? _config;

    private const string AssistantName = "ZERE";

    public AIHandler(
        IAiClient ai,
        ContextBuilder context,
        PluginManager pluginManager,
        RuntimeContext? runtime = null,
        ZereConfig? config = null)
    {
        _ai = ai;
        _context = context;
        _pluginManager = pluginManager;
        _runtime = runtime;
        _config = config;
    }

    public bool CanHandle(string message)
    {
        return true;
    }

    public async Task<string?> HandleAsync(string message)
    {
        var personality = _pluginManager.ActivePersonality;
        var systemPrompt = GetSystemPrompt();

        // Этап 1 (анализ S5): голосовой режим → короткий ответ и жёсткий
        // лимит токенов. Иначе модель печатает простыни, которые TTS
        // проговаривает десятки секунд.
        var isVoice = _runtime?.VoiceMode == true;
        int? maxTokens = null;

        if (isVoice)
        {
            systemPrompt += """

                ГОЛОСОВОЙ РЕЖИМ: ответ будет произнесён вслух. Максимум 1–2 коротких
                предложения. Без списков, кода, markdown и пояснений.
                """;

            if (_config != null && _config.LlmMaxTokens > 0)
                maxTokens = _config.LlmMaxTokens;
        }

        // P1-2: system-промпт в prompt НЕ встраивается — он уходит отдельным
        // полем system в клиенте, иначе модель получала его дважды.
        var prompt = new PromptBuilder()
            .Memory(_context.BuildMemory())
            .History(_context.BuildHistory())
            .UserMessage(message)
            .Build();

        return await _ai.GenerateAsync(prompt, systemPrompt, personality?.Temperature, maxTokens);
    }

    private string GetSystemPrompt()
    {
        var personality = _pluginManager.ActivePersonality;

        if (personality != null)
        {
            return $"""
                Ты — {AssistantName}.

                {personality.SystemPrompt}

                Параметры генерации:
                - Температура: {personality.Temperature}
                - Стиль: {personality.Style}
                """;
        }

        return $"""
            Ты — {AssistantName}.
            Ты персональный AI-ассистент для Windows.
            Отвечай кратко и понятно на русском языке.
            """;
    }
}
