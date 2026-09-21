namespace JARVIS.Core.Handlers;

public class HandlerPipeline
{
    private readonly List<IJarvisHandler> _handlers;

    public HandlerPipeline(IEnumerable<IJarvisHandler> handlers)
    {
        _handlers = handlers.ToList();
    }

    public async Task<string?> HandleAsync(string message)
    {
        foreach (var handler in _handlers)
        {
            try
            {
                if (handler.CanHandle(message))
                {
                    return await handler.HandleAsync(message);
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Pipeline] Ошибка в обработчике {handler.GetType().Name}: {ex.Message}");
            }
        }

        return null;
    }
}
