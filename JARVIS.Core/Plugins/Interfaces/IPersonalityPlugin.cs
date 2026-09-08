namespace JARVIS.Core.Plugins.Interfaces;

public interface IPersonalityPlugin : IPlugin
{
    string SystemPrompt { get; }
    float Temperature { get; }
    PersonalityStyle Style { get; }
    string[] GetAvailableStyles();
    void SetStyle(string styleName);
}

public enum PersonalityStyle
{
    Friendly,
    Formal,
    Sarcastic,
    Professional,
    Casual,
    Custom
}
