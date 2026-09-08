using JARVIS.AI;
using JARVIS.Core.AI;
using JARVIS.Core.Configuration;

namespace JARVIS.Core.Handlers;

public class AIHandler : IJarvisHandler
{
    private readonly OllamaClient _ai;
    private readonly ContextBuilder _context = new();

    private const string AssistantName = "JARVIS";

    public AIHandler()
    {
        var config = JarvisConfig.Load();
        _ai = new OllamaClient(config.Model);
    }

    public bool CanHandle(string message)
    {
        // AI всегда последний обработчик.
        return true;
    }

    public async Task<string> HandleAsync(string message)
    {
        var prompt = new PromptBuilder()
            .SystemPrompt(AssistantName)
            .Memory(_context.BuildMemory())
            .History(_context.BuildHistory())
            .UserMessage(message)
            .Build();

        return await _ai.GenerateAsync(prompt);
    }
}