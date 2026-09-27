using JARVIS.AI;
using JARVIS.Core.AI;
using JARVIS.Core.Configuration;
using JARVIS.Core.Plugins;

namespace JARVIS.Core.Handlers;

public class AIHandler : IJarvisHandler
{
    private readonly OllamaClient _ai;
    private readonly ContextBuilder _context;
    private readonly PluginManager _pluginManager;

    private const string AssistantName = "JARVIS";

    public AIHandler(OllamaClient ai, ContextBuilder context, PluginManager pluginManager)
    {
        _ai = ai;
        _context = context;
        _pluginManager = pluginManager;
    }

    public bool CanHandle(string message)
    {
        return true;
    }

    public async Task<string?> HandleAsync(string message)
    {
        var personality = _pluginManager.ActivePersonality;
        var systemPrompt = GetSystemPrompt();

        var prompt = new PromptBuilder()
            .SystemPrompt(systemPrompt)
            .Memory(_context.BuildMemory())
            .History(_context.BuildHistory())
            .UserMessage(message)
            .Build();

        return await _ai.GenerateAsync(prompt, systemPrompt, personality?.Temperature);
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
