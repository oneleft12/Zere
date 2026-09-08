namespace JARVIS.Core.Plugins.Interfaces;

public interface ICommandHandlerPlugin : IPlugin
{
    string[] SupportedCommands { get; }
    bool CanHandle(string message);
    Task<string> HandleAsync(string message);
}
