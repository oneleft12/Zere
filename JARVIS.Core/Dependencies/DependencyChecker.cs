using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using JARVIS.AI;
using JARVIS.Core.Configuration;
using Microsoft.Data.Sqlite;

namespace JARVIS.Core.Dependencies;

public class DependencyChecker
{
    private readonly JarvisConfig _config;
    private readonly HttpClient _http = new();
    private readonly List<DependencyResult> _results = new();

    private string _ollamaUrl = "http://localhost:11434";

    public DependencyChecker(JarvisConfig config)
    {
        _config = config;
        _ollamaUrl = OllamaUrlResolver.Resolve() ?? _ollamaUrl;
        _http.BaseAddress = new Uri(_ollamaUrl);
        _http.Timeout = TimeSpan.FromSeconds(3);
    }

    public List<DependencyResult> RunAll()
    {
        _results.Clear();

        CheckOllama();
        CheckModel();
        CheckSQLite();
        CheckWhisper();
        CheckPiper();

        return _results;
    }

    public bool AllCriticalPassed()
    {
        return _results
            .Where(r => r.Critical)
            .All(r => r.Status == CheckStatus.Ok);
    }

    public void PrintReport()
    {
        Console.WriteLine("Проверка зависимостей:\n");

        foreach (var r in _results)
        {
            var icon = r.Status switch
            {
                CheckStatus.Ok => "[OK]",
                CheckStatus.Missing => "[!!]",
                CheckStatus.Warning => "[~~]",
                _ => "[??]"
            };

            var line = $"  {icon} {r.Name}";

            if (r.Status != CheckStatus.Ok && !string.IsNullOrEmpty(r.Message))
                line += $" — {r.Message}";

            Console.WriteLine(line);
        }

        Console.WriteLine();
    }

    public void OfferInstall()
    {
        var missing = _results.Where(r =>
            r.Status != CheckStatus.Ok && r.Critical).ToList();

        if (missing.Count == 0)
            return;

        Console.WriteLine("Хотите установить недостающие зависимости? (д/н): ");

        var answer = Console.ReadLine()?.Trim().ToLower();

        if (answer != "д" && answer != "да" && answer != "y" && answer != "yes")
            return;

        Console.WriteLine();

        foreach (var dep in missing)
        {
            Console.Write($"  Установить {dep.Name}? (д/н): ");
            var choice = Console.ReadLine()?.Trim().ToLower();

            if (choice == "д" || choice == "да" || choice == "y" || choice == "yes")
            {
                Console.WriteLine();
                InstallDependency(dep);
                Console.WriteLine();
            }
            else
            {
                Console.WriteLine($"  Пропущено: {dep.Name}\n");
            }
        }

        Console.WriteLine("Повторная проверка...\n");
        RunAll();
        PrintReport();
    }

    private void InstallDependency(DependencyResult dep)
    {
        if (dep.Name == "Ollama")
            InstallOllama();
        else if (dep.Name.StartsWith("Модель"))
            InstallModel();
        else if (dep.Name.StartsWith("SQLite"))
            InstallSQLite();
        else
            Console.WriteLine($"  Нет способа автоматической установки: {dep.Name}");
    }

    private void InstallOllama()
    {
        Console.WriteLine("  Проверяю, установлен ли Ollama...");

        if (CommandExists("ollama"))
        {
            Console.WriteLine("  Ollama найдена. Запускаю сервер...");
            StartOllama();
            return;
        }

        Console.WriteLine("  Ollama не найдена.");
        Console.WriteLine("  Скачайте с https://ollama.com/download");
        Console.WriteLine("  и установите вручную.\n");
        Console.WriteLine("  После установки нажмите Enter...");
        Console.ReadLine();

        Console.WriteLine("  Запускаю Ollama...");
        StartOllama();
    }

    private void StartOllama()
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "ollama",
                Arguments = "serve",
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };

            Process.Start(psi);

            Thread.Sleep(3000);

            try
            {
                var response = _http.GetAsync("/api/tags").Result;
                if (response.IsSuccessStatusCode)
                {
                    Console.WriteLine("  Ollama запущена.");
                    return;
                }
            }
            catch { }

            Console.WriteLine("  Ollama запущена, но сервер может ещё стартовать.");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  Не удалось запустить Ollama: {ex.Message}");
            Console.WriteLine("  Запустите вручную: ollama serve");
        }
    }

    private void InstallModel()
    {
        if (!CommandExists("ollama"))
        {
            Console.WriteLine("  Ollama не установлена. Сначала установите Ollama.");
            return;
        }

        Console.WriteLine($"  Скачиваю модель {_config.Model}...");
        Console.WriteLine("  Это может занять несколько минут.\n");

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "ollama",
                Arguments = $"pull {_config.Model}",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };

            var process = Process.Start(psi);

            if (process != null)
            {
                process.OutputDataReceived += (s, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                        Console.WriteLine($"    {e.Data}");
                };
                process.ErrorDataReceived += (s, e) =>
                {
                    if (!string.IsNullOrEmpty(e.Data))
                        Console.WriteLine($"    {e.Data}");
                };

                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();

                if (process.ExitCode == 0)
                    Console.WriteLine($"\n  Модель {_config.Model} установлена.");
                else
                    Console.WriteLine($"\n  Ошибка установки модели (код {process.ExitCode}).");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  Ошибка: {ex.Message}");
        }
    }

    private void InstallSQLite()
    {
        Console.WriteLine("  Проверяю NuGet пакеты...");

        var projectDir = FindProjectRoot();

        if (string.IsNullOrEmpty(projectDir))
        {
            Console.WriteLine("  Не удалось найти корень проекта.");
            Console.WriteLine("  Выполните вручную: dotnet restore");
            return;
        }

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "dotnet",
                Arguments = "restore",
                WorkingDirectory = projectDir,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };

            var process = Process.Start(psi);
            process?.WaitForExit();

            if (process?.ExitCode == 0)
                Console.WriteLine("  NuGet пакеты восстановлены.");
            else
                Console.WriteLine("  Ошибка восстановления. Выполните: dotnet restore");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  Ошибка: {ex.Message}");
            Console.WriteLine("  Выполните вручную: dotnet restore");
        }
    }

    private string? FindProjectRoot()
    {
        var dir = Directory.GetCurrentDirectory();

        while (dir != null)
        {
            if (File.Exists(Path.Combine(dir, "JARVIS.slnx")))
                return dir;

            dir = Directory.GetParent(dir)?.FullName;
        }

        return null;
    }

    private void CheckOllama()
    {
        try
        {
            var response = _http.GetAsync("/api/tags").Result;

            if (response.IsSuccessStatusCode)
            {
                _results.Add(new DependencyResult
                {
                    Name = "Ollama",
                    Status = CheckStatus.Ok,
                    Critical = true
                });
            }
            else
            {
                _results.Add(new DependencyResult
                {
                    Name = "Ollama",
                    Status = CheckStatus.Missing,
                    Critical = true,
                    Message = "Сервер отвечает, но вернул ошибку."
                });
            }
        }
        catch
        {
            _results.Add(new DependencyResult
            {
                Name = "Ollama",
                Status = CheckStatus.Missing,
                Critical = true,
                Message = $"Сервер недоступен ({_ollamaUrl})"
            });
        }
    }

    private void CheckModel()
    {
        try
        {
            var response = _http.GetAsync("/api/tags").Result;

            if (!response.IsSuccessStatusCode)
            {
                _results.Add(new DependencyResult
                {
                    Name = $"Модель ({_config.Model})",
                    Status = CheckStatus.Missing,
                    Critical = true,
                    Message = "Ollama недоступна."
                });
                return;
            }

            var json = response.Content.ReadAsStringAsync().Result;
            var doc = JsonDocument.Parse(json);

            var models = doc.RootElement
                .GetProperty("models")
                .EnumerateArray()
                .Select(m => m.GetProperty("name").GetString() ?? "")
                .ToList();

            var found = models.Any(m =>
                m.StartsWith(_config.Model, StringComparison.OrdinalIgnoreCase));

            if (found)
            {
                _results.Add(new DependencyResult
                {
                    Name = $"Модель ({_config.Model})",
                    Status = CheckStatus.Ok,
                    Critical = true
                });
            }
            else
            {
                var available = models.Count > 0
                    ? string.Join(", ", models.Take(5))
                    : "нет моделей";

                _results.Add(new DependencyResult
                {
                    Name = $"Модель ({_config.Model})",
                    Status = CheckStatus.Missing,
                    Critical = true,
                    Message = $"Не найдена. Доступные: {available}"
                });
            }
        }
        catch
        {
            _results.Add(new DependencyResult
            {
                Name = $"Модель ({_config.Model})",
                Status = CheckStatus.Warning,
                Critical = true,
                Message = "Не удалось проверить."
            });
        }
    }

    private void CheckSQLite()
    {
        try
        {
            var folder = Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData),
                "JARVIS");

            Directory.CreateDirectory(folder);

            var dbPath = Path.Combine(folder, "jarvis.db");

            using var connection = new SqliteConnection(
                $"Data Source={dbPath}");

            connection.Open();

            var command = connection.CreateCommand();
            command.CommandText = "SELECT 1";
            command.ExecuteScalar();

            connection.Close();

            _results.Add(new DependencyResult
            {
                Name = "SQLite",
                Status = CheckStatus.Ok,
                Critical = true
            });
        }
        catch (DllNotFoundException)
        {
            _results.Add(new DependencyResult
            {
                Name = "SQLite",
                Status = CheckStatus.Missing,
                Critical = true,
                Message = "Native SQLite библиотека не найдена. Нужно восстановить пакеты."
            });
        }
        catch (Exception ex)
        {
            _results.Add(new DependencyResult
            {
                Name = "SQLite",
                Status = CheckStatus.Missing,
                Critical = true,
                Message = ex.Message
            });
        }
    }

    private void CheckWhisper()
    {
        if (!_config.VoiceEnabled)
        {
            _results.Add(new DependencyResult
            {
                Name = "Whisper (голос)",
                Status = CheckStatus.Ok,
                Critical = false,
                Message = "Отключен в конфиге."
            });
            return;
        }

        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory,
                "..", "..", "..", ".."));

        var modelPath = Path.Combine(root, "JARVIS.Voice", "Models", "ggml-base.bin");

        if (File.Exists(modelPath))
        {
            _results.Add(new DependencyResult
            {
                Name = "Whisper (модель)",
                Status = CheckStatus.Ok,
                Critical = false
            });
        }
        else
        {
            _results.Add(new DependencyResult
            {
                Name = "Whisper (модель)",
                Status = CheckStatus.Missing,
                Critical = false,
                Message = $"Файл не найден: {modelPath}"
            });
        }
    }

    private void CheckPiper()
    {
        if (!_config.VoiceEnabled)
        {
            _results.Add(new DependencyResult
            {
                Name = "Piper (TTS)",
                Status = CheckStatus.Ok,
                Critical = false,
                Message = "Отключен в конфиге."
            });
            return;
        }

        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory,
                "..", "..", "..", ".."));

        var piperDir = Path.Combine(root, "JARVIS.Voice", "Piper");

        if (Directory.Exists(piperDir) &&
            Directory.GetFiles(piperDir, "*.onnx").Length > 0)
        {
            _results.Add(new DependencyResult
            {
                Name = "Piper (TTS)",
                Status = CheckStatus.Ok,
                Critical = false
            });
        }
        else
        {
            _results.Add(new DependencyResult
            {
                Name = "Piper (TTS)",
                Status = CheckStatus.Missing,
                Critical = false,
                Message = $"Голосовые модели не найдены в {piperDir}"
            });
        }
    }

    private static bool CommandExists(string command)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = command,
                Arguments = "--version",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            var process = Process.Start(psi);
            process?.WaitForExit(3000);
            return process?.ExitCode == 0;
        }
        catch
        {
            return false;
        }
    }
}

public class DependencyResult
{
    public string Name { get; set; } = "";
    public CheckStatus Status { get; set; }
    public bool Critical { get; set; }
    public string Message { get; set; } = "";
}

public enum CheckStatus
{
    Ok,
    Missing,
    Warning
}
