using JARVIS.Core.Handlers;
using JARVIS.Core.Plugins;
using JARVIS.Memory.Database;

namespace JARVIS.Core;

public class JarvisEngine
{
    private readonly HandlerPipeline _pipeline;
    private readonly MemoryExtractor _extractor;
    private readonly PluginManager _pluginManager;
    private readonly ConversationRepository _conversations;

    public PluginManager PluginManager => _pluginManager;

    public JarvisEngine(HandlerPipeline pipeline, MemoryExtractor extractor, PluginManager pluginManager, ConversationRepository conversations)
    {
        _pipeline = pipeline;
        _extractor = extractor;
        _pluginManager = pluginManager;
        _conversations = conversations;
    }

    public async Task<string> ProcessAsync(string message)
    {
        try
        {
            _extractor.TryExtract(message);

            var result = await _pipeline.HandleAsync(message);

            var answer = result ?? "Команда не распознана.";

            SaveHistory(message, answer);

            return answer;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[JarvisEngine] Ошибка: {ex.Message}");
            return $"Произошла ошибка: {ex.Message}";
        }
    }

    /// <summary>
    /// Сохраняет пару (запрос, ответ) в историю диалогов.
    /// Best-effort: сбой истории не должен ломать ответ пользователю.
    /// </summary>
    private void SaveHistory(string message, string answer)
    {
        try
        {
            _conversations.Save(message, answer);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[JarvisEngine] Не удалось сохранить историю: {ex.Message}");
        }
    }
}
