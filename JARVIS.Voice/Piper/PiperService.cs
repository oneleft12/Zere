using System.Diagnostics;
using System.Text.RegularExpressions;

namespace JARVIS.Voice.Piper;

public class PiperService
{
    public bool IsLoaded { get; private set; }

    private readonly string _piperDir;
    private readonly string _espeakDataPath;
    private string _currentVoice = "ru_RU-irina-medium";
    private string? _piperExe;
    private string? _cachedModelPath;

    public string CurrentVoice => _currentVoice;

    public PiperService()
    {
        // Путь строится относительно AppContext.BaseDirectory с учётом структуры проекта:
        // bin/Debug/net10.0/ → ../../.. → корень решения, затем JARVIS.Voice/Piper.
        // Если структура проекта изменится, этот путь нужно обновить.
        var root = Path.GetFullPath(
            Path.Combine(AppContext.BaseDirectory, "..", "..", "..", ".."));

        _piperDir = Path.Combine(root, "JARVIS.Voice", "Piper");
        _espeakDataPath = Path.Combine(_piperDir, "espeak-ng-data");
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

        if (Directory.Exists(_espeakDataPath))
            Console.WriteLine($"[Piper] espeak-ng-data: {_espeakDataPath}");
        else
            Console.WriteLine($"[Piper] ⚠ espeak-ng-data не найден: {_espeakDataPath}");

        Console.WriteLine($"[Piper] Загружен. Голос: {_currentVoice}");
        return true;
    }

    public async Task<string> SpeakAsync(string text)
    {
        // Убираем эмодзи, смайлики и «ролевые» пометки — TTS не должен их читать
        text = StripEmotions(text);

        if (string.IsNullOrWhiteSpace(text))
            return "";

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
            // Кинематографичный баритон:
            // --length_scale 1.15 — медленная, уверенная подача
            // --noise_scale 0.35 — минимум шума синтеза (было 0.45, шипело)
            // --noise_w 0.65 — стабильная интонация, без металличности
            // --sentence_silence 0.4 — тишина после предложения (не обрезает окончания)
            var psi = new ProcessStartInfo
            {
                FileName = _piperExe,
                Arguments = $"--model \"{_cachedModelPath}\" " +
                           $"--output_file \"{outputFile}\" " +
                           $"--length_scale 1.15 " +
                           $"--noise_scale 0.35 " +
                           $"--noise_w 0.65 " +
                           $"--sentence_silence 0.4",
                UseShellExecute = false,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            // Указываем путь к данным espeak-ng, чтобы piper мог найти phoneme данные
            if (Directory.Exists(_espeakDataPath))
            {
                psi.EnvironmentVariables["ESPEAKDATA_PATH"] = _espeakDataPath;
                psi.EnvironmentVariables["ESPEAK_DATA_PATH"] = _espeakDataPath;
            }

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

    /// <summary>
    /// Убирает из текста всё, что TTS не должен произносить:
    /// эмодзи, текстовые смайлики, «ролевые» пометки (*улыбается*, (томно)),
    /// markdown-символы и Markdown-эмодзи вроде :smile:.
    /// </summary>
    private static string StripEmotions(string text)
    {
        if (string.IsNullOrEmpty(text))
            return text;

        // Ролевые пометки в скобках: (улыбается), (смеётся), (задумчиво)
        text = Regex.Replace(text, @"\([^)]*[а-яёА-ЯЁ]{3,}[^)]*\)", " ");

        // Ролевые пометки в *звёздочках*: *улыбается*, *качает головой*
        text = Regex.Replace(text, @"\*[^*]*[а-яёА-ЯЁ]{3,}[^*]*\*", " ");

        // Markdown-эмодзи :smile:, :heart:
        text = Regex.Replace(text, @":[a-z_0-9]+:", " ");

        // Текстовые смайлики: :) ;) :D :( :P <3 =) и т.п.
        text = Regex.Replace(text, @"[:;=8][\-^']?[)(DPp/\\|]", " ");
        text = Regex.Replace(text, @"[)(DPp/\\|][\-^']?[:;=8]", " ");
        text = Regex.Replace(text, @"<3", " ");

        // Юникод-эмодзи и символы (суррогатные пары, Variation Selector, ZWJ)
        text = Regex.Replace(text,
            @"[\uD800-\uDBFF][\uDC00-\uDFFF]|\uFE0F|\u200D|[\u2600-\u27BF]|\u2190-\u21FF|\u2B00-\u2BFF|\u2700-\u27BF]",
            "");

        // Убираем markdown-разметку: **bold**, *italic*, `code`, ## заголовки
        text = Regex.Replace(text, @"[*_`#]{1,3}([^*_`#]+)[*_`#]{1,3}", "$1");
        text = Regex.Replace(text, @"[*_`#~>|-]{2,}", " ");

        // Схлопываем пробелы
        text = Regex.Replace(text, @"\s{2,}", " ").Trim();

        return text;
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
