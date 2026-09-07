namespace JARVIS.Core.Handlers;

public interface IJarvisHandler
{
    bool CanHandle(string message);

    Task<string> HandleAsync(string message);
}