using System.Diagnostics;
using System.Net.Http.Json;
using System.Text.Json;
using JARVIS.AI;
using JARVIS.Core.Configuration;
using Microsoft.Data.Sqlite;

namespace JARVIS.Core.Dependencies;

public class DependencyChecker : IDisposable
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

            if (r.Status != CheckStatus.Ok)
            {
                if (!string.IsNullOrEmpty(r.InstallCommand))
                    Console.WriteLine($"    Команда: {r.InstallCommand}");
                if (!string.IsNullOrEmpty(r.InstallUrl))
                    Console.WriteLine($"    Ссылка: {r.InstallUrl}");
            }
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

        // Offer to install non-critical voice dependencies
        var voiceMissing = _results.Where(r =>
            r.Status != CheckStatus.Ok && !r.Critical &&
            (r.Name.Contains("Whisper") || r.Name.Contains("Piper"))).ToList();

        if (voiceMissing.Count > 0)
        {
            Console.WriteLine("\nГолосовые компоненты не установлены:");
            foreach (var dep in voiceMissing)
                Console.WriteLine($"  - {dep.Name}");

            if (AskConfirmation("\nУстановить голосовые компоненты?"))
            {
                Console.WriteLine();
                foreach (var dep in voiceMissing)
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
            }
        }

        Console.WriteLine("Повторная проверка...\n");
        RunAll();
        PrintReport();
    }

    private static bool AskConfirmation(string prompt)
    {
        Console.Write($"  {prompt} (д/н): ");
        var answer = Console.ReadLine()?.Trim().ToLower();
        return answer == "д" || answer == "да" || answer == "y" || answer == "yes";
    }

    private static bool CheckWinget()
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "winget",
                Arguments = "--version",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            using var process = Process.Start(psi);
            process?.WaitForExit(3000);
            return process?.ExitCode == 0;
        }
        catch
        {
            return false;
        }
    }

    private void ExecuteCommandWithConfirmation(string command, string description)
    {
        Console.WriteLine($"  {description}");
        Console.WriteLine($"  Команда: {command}");

        if (!AskConfirmation("Выполнить?"))
        {
            Console.WriteLine("  Пропущено.");
            return;
        }

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = $"/c {command}",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            using var process = Process.Start(psi);

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
                    Console.WriteLine("  Готово.");
                else
                    Console.WriteLine($"  Ошибка (код {process.ExitCode}).");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  Ошибка: {ex.Message}");
        }
    }

    private void InstallDependency(DependencyResult dep)
    {
        if (dep.Name == "Ollama")
            InstallOllama();
        else if (dep.Name.StartsWith("Модель"))
            InstallModel();
        else if (dep.Name.StartsWith("SQLite"))
            InstallSQLite();
        else if (dep.Name.Contains("Whisper"))
            InstallWhisper();
        else if (dep.Name.Contains("Piper"))
            InstallPiper();
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

        if (CheckWinget())
        {
            Console.WriteLine("  winget доступен. Предлагаю автоматическую установку.");
            ExecuteCommandWithConfirmation(
                "winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements",
                "Устанавливаю Ollama через winget...");
        }
        else
        {
            Console.WriteLine("  winget недоступен.");
            Console.WriteLine("  Скачайте Ollama вручную:");
            Console.WriteLine("  https://ollama.com/download\n");

            if (!AskConfirmation("Открыть страницу загрузки в браузере?"))
            {
                Console.WriteLine("  Установите Ollama вручную и нажмите Enter...");
                Console.ReadLine();
            }
            else
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "https://ollama.com/download",
                        UseShellExecute = true
                    });
                }
                catch
                {
                    Console.WriteLine("  Не удалось открыть браузер. Перейдите по ссылке вручную.");
                }

                Console.WriteLine("  После установки нажмите Enter...");
                Console.ReadLine();
            }
        }

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

            // Fire-and-forget: ollama serve process runs in background for the entire JARVIS session.
            // Using `using` here would kill the process when the scope ends.
            var process = Process.Start(psi);

            Thread.Sleep(3000);

            try
            {
                // .GetAwaiter().GetResult() is used because this is called from synchronous context.
                var response = _http.GetAsync("/api/tags").GetAwaiter().GetResult();
                if (response.IsSuccessStatusCode)
                {
                    Console.WriteLine("  Ollama запущена.");
                    return;
                }
            }
            catch (HttpRequestException)
        {
            // HTTP request failed — Ollama may not be running
        }

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

        var command = $"ollama pull {_config.Model}";
        Console.WriteLine($"  Скачиваю модель {_config.Model}...");
        Console.WriteLine($"  Команда: {command}");

        if (!AskConfirmation("Выполнить?"))
        {
            Console.WriteLine("  Пропущено.");
            return;
        }

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

            using var process = Process.Start(psi);

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

            using var process = Process.Start(psi);
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

    private void InstallWhisper()
    {
        Console.WriteLine("  Модель Whisper (ggml-base.bin) не найдена.");

        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        var modelsDir = Path.Combine(root, "JARVIS.Voice", "Models");
        Directory.CreateDirectory(modelsDir);

        var targetFile = Path.Combine(modelsDir, "ggml-base.bin");

        if (File.Exists(targetFile))
        {
            Console.WriteLine("  Модель уже скачана.");
            return;
        }

        var url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin";
        Console.WriteLine($"  Скачиваю модель Whisper (~150 МБ)...");
        Console.WriteLine($"  Источник: {url}");
        Console.WriteLine($"  Куда: {targetFile}\n");

        if (!AskConfirmation("Скачать?"))
        {
            Console.WriteLine("  Пропущено.");
            return;
        }

        // Try curl first (available on most Windows 10+)
        if (CommandExists("curl"))
        {
            ExecuteCommandWithConfirmation(
                $"curl -L -o \"{targetFile}\" \"{url}\"",
                "Скачиваю через curl...");
        }
        // Fallback to PowerShell Invoke-WebRequest
        else if (CommandExists("powershell"))
        {
            ExecuteCommandWithConfirmation(
                $"powershell -Command \"Invoke-WebRequest -Uri '{url}' -OutFile '{targetFile}'\"",
                "Скачиваю через PowerShell...");
        }
        else
        {
            Console.WriteLine("  Neither curl nor PowerShell found.");
            Console.WriteLine("  Скачайте вручную:");
            Console.WriteLine($"  {url}");
            Console.WriteLine($"  Сохраните в: {targetFile}");
            return;
        }

        if (File.Exists(targetFile))
            Console.WriteLine("  Модель Whisper установлена.");
        else
            Console.WriteLine("  Ошибка: файл не был скачан.");
    }

    private void InstallPiper()
    {
        Console.WriteLine("  Piper (TTS) не найден.");

        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        var piperDir = Path.Combine(root, "JARVIS.Voice", "Piper");
        Directory.CreateDirectory(piperDir);

        // Check if piper.exe exists
        var piperExe = Path.Combine(piperDir, "piper.exe");
        var piperLinux = Path.Combine(piperDir, "piper");

        if (!File.Exists(piperExe) && !File.Exists(piperLinux))
        {
            Console.WriteLine("  Piper не установлен. Нужно скачать piper.exe.");
            Console.WriteLine("  Источник: https://github.com/rhasspy/piper/releases\n");

            if (AskConfirmation("Открыть страницу загрузки Piper в браузере?"))
            {
                try
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = "https://github.com/rhasspy/piper/releases",
                        UseShellExecute = true
                    });
                }
                catch
                {
                    Console.WriteLine("  Не удалось открыть браузер.");
                }
            }

            Console.WriteLine("\n  Скачайте piper_windows_amd64.zip");
            Console.WriteLine("  Распакуйте piper.exe в:");
            Console.WriteLine($"  {piperDir}\n");
            Console.WriteLine("  После установки нажмите Enter...");
            Console.ReadLine();
        }

        // Check for voice models
        var onnxFiles = Directory.GetFiles(piperDir, "*.onnx");
        if (onnxFiles.Length == 0)
        {
            Console.WriteLine("  Голосовые модели не найдены.");
            Console.WriteLine("  Нужна модель ru_RU-irina-medium.onnx\n");

            if (AskConfirmation("Скачать русскую голосовую модель?"))
            {
                var voiceUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx";
                var voiceTarget = Path.Combine(piperDir, "ru_RU-irina-medium.onnx");

                if (CommandExists("curl"))
                {
                    ExecuteCommandWithConfirmation(
                        $"curl -L -o \"{voiceTarget}\" \"{voiceUrl}\"",
                        "Скачиваю голосовую модель...");
                }
                else if (CommandExists("powershell"))
                {
                    ExecuteCommandWithConfirmation(
                        $"powershell -Command \"Invoke-WebRequest -Uri '{voiceUrl}' -OutFile '{voiceTarget}'\"",
                        "Скачиваю голосовую модель через PowerShell...");
                }

                // Also download the JSON config for the voice
                var configUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json";
                var configTarget = Path.Combine(piperDir, "ru_RU-irina-medium.onnx.json");

                if (CommandExists("curl"))
                {
                    ExecuteCommandWithConfirmation(
                        $"curl -L -o \"{configTarget}\" \"{configUrl}\"",
                        "Скачиваю конфигурацию голоса...");
                }

                if (File.Exists(voiceTarget))
                    Console.WriteLine("  Голосовая модель установлена.");
                else
                    Console.WriteLine("  Ошибка: модель не была скачана.");
            }
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
            // .GetAwaiter().GetResult() is used because this is called from synchronous context.
            var response = _http.GetAsync("/api/tags").GetAwaiter().GetResult();

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
                Message = $"Сервер недоступен ({_ollamaUrl})",
                InstallUrl = "https://ollama.com/download",
                InstallCommand = CheckWinget() ? "winget install Ollama.Ollama" : null
            });
        }
    }

    private void CheckModel()
    {
        try
        {
            // .GetAwaiter().GetResult() is used because this is called from synchronous context.
            var response = _http.GetAsync("/api/tags").GetAwaiter().GetResult();

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

            var json = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
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
                    Message = $"Не найдена. Доступные: {available}",
                    InstallCommand = $"ollama pull {_config.Model}"
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
                Message = $"Файл не найден: {modelPath}",
                InstallUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
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
                Message = $"Голосовые модели не найдены в {piperDir}",
                InstallUrl = "https://github.com/rhasspy/piper/releases"
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

            using var process = Process.Start(psi);
            process?.WaitForExit(3000);
            return process?.ExitCode == 0;
        }
        catch (System.ComponentModel.Win32Exception)
        {
            // Command not found on system PATH
            return false;
        }
        catch (InvalidOperationException)
        {
            // Process start failed (e.g., invalid file name)
            return false;
        }
    }

    public void OfferVoiceInstall()
    {
        var voiceMissing = _results.Where(r =>
            r.Status != CheckStatus.Ok &&
            (r.Name.Contains("Whisper") || r.Name.Contains("Piper"))).ToList();

        if (voiceMissing.Count == 0)
            return;

        Console.WriteLine("Голосовые компоненты не установлены:");
        foreach (var dep in voiceMissing)
            Console.WriteLine($"  - {dep.Name} — {dep.Message}");

        Console.Write("\nУстановить голосовые компоненты? (д/н): ");
        var answer = Console.ReadLine()?.Trim().ToLower();

        if (answer != "д" && answer != "да" && answer != "y" && answer != "yes")
            return;

        Console.WriteLine();

        foreach (var dep in voiceMissing)
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

    public void Dispose()
    {
        _http.Dispose();
        GC.SuppressFinalize(this);
    }
}

public class DependencyResult
{
    public string Name { get; set; } = "";
    public CheckStatus Status { get; set; }
    public bool Critical { get; set; }
    public string Message { get; set; } = "";
    public string? InstallUrl { get; set; }
    public string? InstallCommand { get; set; }
}

public enum CheckStatus
{
    Ok,
    Missing,
    Warning
}
