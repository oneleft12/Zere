using System.Diagnostics;

namespace ZERE.AI;

/// <summary>
/// Права «только владелец» на файлы с секретами (config/ai.json, panel.token).
///
/// Имя класса не <c>FileAccess</c> намеренно: так называется
/// <c>System.IO.FileAccess</c>, и короткое имя давало CS0104 в файлах, где
/// подключён System.IO.
///
/// Зачем: на Windows <c>File.SetUnixFileMode</c> и Python-овый <c>chmod</c>
/// меняют лишь флаг «только чтение» и ACL не трогают. Файл с ключом
/// наследовал права папки, а это <c>BUILTIN\Пользователи: Read</c> и
/// <c>Authenticated Users: Modify</c> — то есть ключ мог прочитать и
/// подменить любой локальный пользователь, хотя docs/AI_PROVIDERS.md и
/// AGENTS.md обещают 0600. Проверено на боевом файле через Get-Acl.
///
/// Windows-аналог 0600 — не chmod, а icacls: снять наследование
/// (<c>/inheritance:r</c>) и выдать полный доступ только текущему
/// пользователю (<c>/grant:r</c>). POSIX-ветка — обычный 0600.
/// Паритет с zere/core/security/file_access.py.
///
/// Ошибки намеренно проглатываются: недоступность icacls или чужой
/// файловой системы не должна ломать сохранение настроек.
/// </summary>
public static class SecretFileAccess
{
    private const int IcaclsTimeoutMilliseconds = 15_000;

    public static void RestrictToOwner(string path)
    {
        if (!OperatingSystem.IsWindows())
        {
            try
            {
                File.SetUnixFileMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
            catch (Exception)
            {
                // Чужая ФС: права не критичны, файл всё равно вне git
            }

            return;
        }

        RestrictToOwnerWindows(path);
    }

    private static void RestrictToOwnerWindows(string path)
    {
        var systemRoot = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
        var icacls = Path.Combine(systemRoot, "System32", "icacls.exe");

        if (!File.Exists(icacls))
            return;

        foreach (var principal in WindowsPrincipals())
        {
            try
            {
                var startInfo = new ProcessStartInfo
                {
                    FileName = icacls,
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };

                // ArgumentList, а не Arguments: путь с пробелами и имя учётки
                // не требуют ручного экранирования. Аргументы добавляются до
                // старта процесса — после Process.Start они уже не применятся.
                startInfo.ArgumentList.Add(path);
                startInfo.ArgumentList.Add("/inheritance:r");
                startInfo.ArgumentList.Add("/grant:r");
                startInfo.ArgumentList.Add($"{principal}:F");

                using var process = Process.Start(startInfo);

                if (process is null)
                    continue;

                process.StandardOutput.ReadToEnd();
                process.StandardError.ReadToEnd();

                if (!process.WaitForExit(IcaclsTimeoutMilliseconds))
                {
                    try
                    {
                        process.Kill(entireProcessTree: true);
                    }
                    catch (Exception)
                    {
                        // Процесс уже завершился — не мешает.
                    }

                    continue;
                }

                if (process.ExitCode == 0)
                    return;
            }
            catch (Exception)
            {
                // Права не должны ломать сохранение настроек.
            }
        }
    }

    /// <summary>
    /// Кандидаты имени текущего пользователя для icacls, от точного к простому.
    /// Для доменной учётки нужно <c>ДОМЕН\пользователь</c>, для локальной
    /// хватает имени; берётся первый, который icacls принял.
    /// </summary>
    private static IEnumerable<string> WindowsPrincipals()
    {
        var user = Environment.UserName;
        var domain = Environment.UserDomainName;

        if (!string.IsNullOrWhiteSpace(user) && !string.IsNullOrWhiteSpace(domain))
            yield return $"{domain}\\{user}";

        if (!string.IsNullOrWhiteSpace(user))
            yield return user;
    }
}
