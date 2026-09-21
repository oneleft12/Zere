using JARVIS.Voice.Audio;
using JARVIS.Voice.Piper;
using JARVIS.Voice.WakeWord;
using JARVIS.Voice.Whisper;

namespace JARVIS.Voice;

public class VoiceManager : IDisposable
{
    private readonly AudioRecorder _recorder = new();
    private readonly AudioPlayer _player = new();
    private readonly WhisperService _whisper = new();
    private readonly PiperService _piper = new();
    private readonly VoiceConfig _config = new();
    private WakeWordDetector? _wakeWordDetector;

    private readonly Dictionary<string, string> _personalityVoices = new()
    {
        ["Friendly"] = "ru_RU-irina-medium",
        ["Formal"] = "ru_RU-irina-medium",
        ["Sarcastic"] = "ru_RU-dmitri-medium",
        ["Professional"] = "ru_RU-dmitri-medium",
        ["Casual"] = "ru_RU-irina-medium"
    };

    public bool IsVoiceAvailable => _whisper.IsInstalled();
    public bool IsTtsAvailable => _piper.IsLoaded;
    public VoiceConfig Config => _config;

    public bool Initialize(string? personalityStyle = null)
    {
        var voiceName = _config.PiperVoice;

        if (personalityStyle != null &&
            _personalityVoices.TryGetValue(personalityStyle, out var styleVoice))
        {
            voiceName = styleVoice;
        }

        var ttsReady = _piper.Initialize(voiceName);

        if (ttsReady)
        {
            Console.WriteLine($"[Voice] TTS готов. Голос: {_piper.CurrentVoice}");
        }
        else
        {
            Console.WriteLine("[Voice] TTS недоступен. Только текстовый режим.");
        }

        return ttsReady;
    }

    public void SetPersonalityVoice(string style)
    {
        if (_personalityVoices.TryGetValue(style, out var voice))
        {
            _piper.SetVoice(voice);
            Console.WriteLine($"[Voice] Голос изменён на: {voice} (стиль: {style})");
        }
    }

    public async Task<string> ListenAsync()
    {
        if (!_whisper.IsInstalled())
        {
            Console.WriteLine("[Voice] Whisper не установлен.");
            return "";
        }

        var wav = await _recorder.RecordAsync();

        Console.WriteLine("Распознаю речь...");

        return await _whisper.TranscribeAsync(wav);
    }

    public async Task SpeakAsync(string text)
    {
        if (!_piper.IsLoaded)
        {
            Console.WriteLine($"[JARVIS] {text}");
            return;
        }

        var wavFile = await _piper.SpeakAsync(text);

        if (!string.IsNullOrEmpty(wavFile))
        {
            string fileToPlay = wavFile;

            // Профессиональная DSP-обработка: EQ, компрессия, нормализация
            if (_config.AudioProcessing)
            {
                var processedFile = AudioProcessor.Process(wavFile);
                fileToPlay = processedFile;
            }

            await _player.PlayAsync(fileToPlay, _config.Volume);

            // Удаляем обработанный файл (если он отличается от оригинального)
            try { if (fileToPlay != wavFile) File.Delete(fileToPlay); } catch { }
            try { File.Delete(wavFile); } catch { }
        }
    }

    public void StopSpeaking()
    {
        _player.Stop();
    }

    #region Wake Word

    /// <summary>
    /// Включает режим wake word и возвращает детектор.
    /// </summary>
    public WakeWordDetector EnableWakeWord()
    {
        _wakeWordDetector?.Dispose();
        _wakeWordDetector = new WakeWordDetector(_config);
        return _wakeWordDetector;
    }

    /// <summary>
    /// Ожидает произнесения ключевого слова.
    /// Возвращает true если обнаружено, false если отмена.
    /// </summary>
    public async Task<bool> WaitForWakeWordAsync(CancellationToken ct = default)
    {
        if (_wakeWordDetector == null)
            return false;

        var result = await _wakeWordDetector.WaitForWakeWordAsync(ct);
        return !string.IsNullOrEmpty(result);
    }

    /// <summary>
    /// Слушает голосовую команду после wake word.
    /// Записывает до тишины (1.5 сек) или максимум 10 секунд.
    /// </summary>
    public async Task<string> ListenCommandAsync()
    {
        if (!_whisper.IsInstalled())
        {
            Console.WriteLine("[Voice] Whisper не установлен.");
            return "";
        }

        var wav = await _recorder.RecordWithVadAsync(maxSeconds: 10, silenceMs: 1500);

        if (string.IsNullOrEmpty(wav) || !File.Exists(wav))
            return "";

        // Проверяем что файл не пустой
        var fileInfo = new FileInfo(wav);
        if (fileInfo.Length < 2000)
        {
            try { File.Delete(wav); } catch { }
            return "";
        }

        Console.WriteLine("🧠 Распознаю команду...");

        var result = await _whisper.TranscribeAsync(wav);

        // Очищаем
        try { File.Delete(wav); } catch { }

        return result;
    }

    #endregion

    public void Dispose()
    {
        _recorder.Dispose();
        _player.Dispose();
        _wakeWordDetector?.Dispose();
        GC.SuppressFinalize(this);
    }
}
