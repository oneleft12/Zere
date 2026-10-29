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

    // Язык ответа добавляется к ЛЮБОМУ системному промпту (в том числе к
    // промпту активной личности): раньше правило было только в SystemPrompt.Zere,
    // а при включённой личности (по умолчанию Friendly) оно вообще не попадало
    // в запрос — малые модели уходили в английский/китайский.
    //
    // Язык берётся из config/config.json (Language, ru|en) — паритет с Python:
    // раньше настройка была декоративной и ответ всегда был русским.
    private string Language()
    {
        var value = _config?.Language?.ToLowerInvariant() ?? "ru";
        return value == "en" ? "en" : "ru";
    }

    private static string LanguageRule(string language) => language == "en"
        ? """


            ANSWER LANGUAGE (main rule):
            — answer only in English;
            — do not switch to Russian or any other language, even if the question is in another language or contains foreign words;
            — foreign words are allowed only in program names, commands, paths and code.
            """
        : """


            ЯЗЫК ОТВЕТА (главное правило):
            — отвечай только на русском языке;
            — не переключайся на английский или любой другой язык, даже если вопрос задан не по-русски или содержит иноязычные слова;
            — иноязычные слова допустимы только в именах программ, командах, путях и коде.
            """;

    private static string VoiceInstruction(string language) => language == "en"
        ? """


            VOICE MODE: the answer will be spoken aloud. At most 1–2 short sentences. No lists, code, markdown or explanations.
            """
        : """


            ГОЛОСОВОЙ РЕЖИМ: ответ будет произнесён вслух. Максимум 1–2 коротких предложения. Без списков, кода, markdown и пояснений.
            """;

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
            systemPrompt += VoiceInstruction(Language());

            if (_config != null && _config.LlmMaxTokens > 0)
                maxTokens = _config.LlmMaxTokens;
        }

        // P1-2: system-промпт в prompt НЕ встраивается — он уходит отдельным
        // полем system в клиенте, иначе модель получала его дважды.
        var prompt = new PromptBuilder(Language())
            .Memory(_context.BuildMemory())
            .History(_context.BuildHistory())
            .UserMessage(message)
            .Build();

        return await _ai.GenerateAsync(prompt, systemPrompt, personality?.Temperature, maxTokens);
    }

    private string GetSystemPrompt()
    {
        var personality = _pluginManager.ActivePersonality;
        var language = Language();
        var rule = LanguageRule(language);
        var intro = language == "en" ? $"You are {AssistantName}." : $"Ты — {AssistantName}.";

        if (personality != null)
        {
            return $"""
                {intro}

                {personality.SystemPrompt}

                Параметры генерации:
                - Температура: {personality.Temperature}
                - Стиль: {personality.Style}{rule}
                """;
        }

        var basePart = language == "en"
            ? "You are a personal AI assistant for Windows.\nAnswer briefly and clearly in English."
            : "Ты персональный AI-ассистент для Windows.\nОтвечай кратко и понятно на русском языке.";

        return $"{intro}\n{basePart}{rule}";
    }
}
