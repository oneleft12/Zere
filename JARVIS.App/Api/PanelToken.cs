using System.Security.Cryptography;

namespace JARVIS.App.Api;

/// <summary>
/// Токен локальной панели (docs/GUI_DEVELOPMENT_PLAN.md §6).
/// 32 байта в hex; создаётся при первом старте, хранится в config/panel.token
/// (файл попадает в .gitignore — токен не должен быть в репозитории).
/// </summary>
public static class PanelToken
{
    private const int TokenLength = 64; // 32 байта в hex

    public static string LoadOrCreate()
    {
        var directory = Path.Combine(Directory.GetCurrentDirectory(), "config");
        Directory.CreateDirectory(directory);

        var path = Path.Combine(directory, "panel.token");

        if (File.Exists(path))
        {
            var existing = File.ReadAllText(path).Trim();

            if (existing.Length == TokenLength && existing.All(Uri.IsHexDigit))
                return existing;
        }

        var bytes = new byte[32];
        RandomNumberGenerator.Fill(bytes);

        var token = Convert.ToHexString(bytes).ToLowerInvariant();
        File.WriteAllText(path, token);

        return token;
    }
}
