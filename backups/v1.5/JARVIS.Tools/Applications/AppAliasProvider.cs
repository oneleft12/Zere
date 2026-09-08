namespace JARVIS.Tools.Applications;

public static class AppAliasProvider
{
    public static readonly Dictionary<string, string> Aliases = new()
    {
        ["дискорд"] = "discord",
        ["discord"] = "discord",

        ["телега"] = "telegram desktop",
        ["телеграм"] = "telegram desktop",
        ["telegram"] = "telegram desktop",

        ["стим"] = "steam",
        ["steam"] = "steam",

        ["хром"] = "google chrome",
        ["chrome"] = "google chrome",
        ["гугл"] = "google chrome",
        ["браузер"] = "google chrome",

        ["код"] = "visual studio code",
        ["vscode"] = "visual studio code",
        ["vs code"] = "visual studio code",

        ["эпик"] = "epic games launcher",
        ["epic"] = "epic games launcher",

        ["спотифай"] = "spotify",
        ["spotify"] = "spotify",

        ["риот"] = "riot client"
    };

    public static List<string> GetAliases(string appName)
    {
        return Aliases
            .Where(x => x.Value.Equals(appName, StringComparison.OrdinalIgnoreCase))
            .Select(x => x.Key)
            .ToList();
    }
}