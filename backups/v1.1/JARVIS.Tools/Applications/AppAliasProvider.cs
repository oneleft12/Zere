namespace JARVIS.Tools.Applications;

public static class AppAliasProvider
{
    public static readonly Dictionary<string, string> Aliases = new()
    {
        { "дискорд", "discord" },
        { "discord", "discord" },

        { "телега", "telegram desktop" },
        { "телеграм", "telegram desktop" },
        { "telegram", "telegram desktop" },

        { "стим", "steam" },
        { "steam", "steam" },

        { "код", "visual studio code" },
        { "vscode", "visual studio code" },
        { "vs code", "visual studio code" },

        { "браузер", "google chrome" },
        { "гугл", "google chrome" },
        { "chrome", "google chrome" },

        { "эпик", "epic games launcher" },
        { "epic", "epic games launcher" },

        { "спотифай", "spotify" },
        { "spotify", "spotify" },

        { "тикток", "tiktok live studio" },

        { "фейсит", "faceit ac" },

        { "exitlag", "exitlag" }
    };
}