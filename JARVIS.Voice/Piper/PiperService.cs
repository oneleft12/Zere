using System.Diagnostics;

namespace JARVIS.Voice.Piper;

public class PiperService
{
    public bool IsLoaded { get; private set; }

    private readonly string _piperDir;
    private string _currentVoice = "ru_RU-irina-medium";
    private string? _piperExe;
    private string? _cachedModelPath;

    public string CurrentVoice => _currentVoice;

    public PiperService()
    {
        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _piperDir = Path.Combine(root, "JARVIS.Voice", "Piper");
    }

    public bool Initialize(string? voiceName = null)
    {
        if (voiceName != null)
            _currentVoice = voiceName;

        _piperExe = FindPiperExecutable();

        if (_piperExe == null)
        {
            Console.WriteLine("[Piper] Исполняемый файл piper не найден.");
            IsLoaded = false;
            return false;
        }

        var modelPath = FindModelPath();

        if (modelPath == null)
        {
            Console.WriteLine($"[Piper] Модель '{_currentVoice}' не найдена в {_piperDir}");
            IsLoaded = false;
            return false;
        }

        _cachedModelPath = modelPath;

        // Clean up old output files older than 1 hour
        CleanupOldOutputs();

        IsLoaded = true;
        Console.WriteLine($"[Piper] Загружен. Голос: {_currentVoice}");
        return true;
    }

    public async Task<string> SpeakAsync(string text)
    {
        if (!IsLoaded || _piperExe == null)
        {
            Console.WriteLine($"[Piper] {text}");
            return "";
        }

        var outputFile = Path.Combine(
            _piperDir,
            $"output_{DateTime.Now:yyyyMMdd_HHmmss}.wav");

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = _piperExe,
                Arguments = $"--model \"{_cachedModelPath}\" --output_file \"{outputFile}\"",
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            using var process = Process.Start(psi);

            if (process == null)
            {
                Console.WriteLine("[Piper] Не удалось запустить процесс.");
                return "";
            }

            await process.StandardInput.WriteAsync(text);
            await process.StandardInput.FlushAsync();
            process.StandardInput.Close();

            await process.WaitForExitAsync();

            if (process.ExitCode != 0)
            {
                var error = await process.StandardError.ReadToEndAsync();
                Console.WriteLine($"[Piper] Ошибка: {error}");
                return "";
            }

            return outputFile;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Piper] Ошибка: {ex.Message}");
            return "";
        }
    }

    private string? FindPiperExecutable()
    {
        var piperDir = Path.Combine(_piperDir, "piper");

        if (File.Exists(piperDir))
            return piperDir;

        var piperExe = Path.Combine(_piperDir, "piper.exe");

        if (File.Exists(piperExe))
            return piperExe;

        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = "piper",
                Arguments = "--version",
                UseShellExecute = false,
                RedirectStandardOutput = true,
                CreateNoWindow = true
            };

            using var process = Process.Start(psi);
            process?.WaitForExit(3000);

            if (process?.ExitCode == 0)
                return "piper";
        }
        catch { }

        return null;
    }

    private string? FindModelPath()
    {
        var modelFile = $"{_currentVoice}.onnx";

        var modelPath = Path.Combine(_piperDir, modelFile);

        if (File.Exists(modelPath))
            return modelPath;

        var onnxFiles = Directory.GetFiles(_piperDir, "*.onnx");

        if (onnxFiles.Length > 0)
            return onnxFiles[0];

        return null;
    }

    public List<string> GetAvailableVoices()
    {
        if (!Directory.Exists(_piperDir))
            return new List<string>();

        return Directory.GetFiles(_piperDir, "*.onnx")
            .Select(f => Path.GetFileNameWithoutExtension(f))
            .ToList();
    }

    public void SetVoice(string voiceName)
    {
        _currentVoice = voiceName;
        _cachedModelPath = null;

        if (IsLoaded)
            Initialize(voiceName);
    }

    private void CleanupOldOutputs()
    {
        try
        {
            var cutoff = DateTime.Now.AddHours(-1);
            var outputFiles = Directory.GetFiles(_piperDir, "output_*.wav");

            foreach (var file in outputFiles)
            {
                var fileInfo = new FileInfo(file);

                if (fileInfo.LastWriteTime < cutoff)
                {
                    try
                    {
                        fileInfo.Delete();
                    }
                    catch
                    {
                        // Ignore individual file deletion failures during cleanup
                    }
                }
            }
        }
        catch
        {
            // Ignore cleanup failures — not critical
        }
    }
}
