using JARVIS.AI;
using JARVIS.Core.AI;
using JARVIS.Core.Configuration;
using JARVIS.Core.Plugins;
using JARVIS.Core.Plugins.Interfaces;

namespace JARVIS.Core.Handlers;

public class AIHandler : IJarvisHandler
{
    private readonly OllamaClient _ai;
    private readonly ContextBuilder _context = new();
    private readonly PluginManager _pluginManager;

    private const string AssistantName = "JARVIS";

    public AIHandler(PluginManager pluginManager)
    {
        _pluginManager = pluginManager;

        var config = JarvisConfig.Load();
        _ai = new OllamaClient(config.Model);
    }

    public bool CanHandle(string message)
    {
        return true;
    }

    public async Task<string> HandleAsync(string message)
    {
        var systemPrompt = GetSystemPrompt();

        var prompt = new PromptBuilder()
            .SystemPrompt(systemPrompt)
            .Memory(_context.BuildMemory())
            .History(_context.BuildHistory())
            .UserMessage(message)
            .Build();

        return await _ai.GenerateAsync(prompt);
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
