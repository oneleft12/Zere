namespace JARVIS.Core.Handlers;

public interface IJarvisHandler
{
    bool CanHandle(string message);

    /// <summary>
    /// Обработать сообщение. Возвращает null, если обработчик не смог
    /// ответить — конвейер передаст сообщение следующему обработчику.
    /// </summary>
    Task<string?> HandleAsync(string message);
}
