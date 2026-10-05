namespace ZERE.Core.Handlers;

public interface IZereHandler
{
    bool CanHandle(string message);

    /// <summary>
    /// Обработать сообщение. Возвращает null, если обработчик не смог
    /// ответить — конвейер передаст сообщение следующему обработчику.
    /// </summary>
    Task<string?> HandleAsync(string message);
}
