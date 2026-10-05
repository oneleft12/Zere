namespace ZERE.Core.Handlers;

public class HandlerPipeline
{
    private readonly List<IZereHandler> _handlers;

    public HandlerPipeline(IEnumerable<IZereHandler> handlers)
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
                    var result = await handler.HandleAsync(message);

                    // null = обработчик не смог ответить → следующий обработчик
                    // (например, память не знает ответа → вопрос уходит в LLM).
                    if (result != null)
                        return result;
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
