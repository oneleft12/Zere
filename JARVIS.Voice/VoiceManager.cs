using JARVIS.Voice.Audio;
using JARVIS.Voice.Piper;
using JARVIS.Voice.Pocket;
using JARVIS.Voice.WakeWord;
using JARVIS.Voice.Whisper;

namespace JARVIS.Voice;

public class VoiceManager : IDisposable
{
    private readonly AudioRecorder _recorder = new();
    private readonly AudioPlayer _player = new();
    private readonly WhisperService _whisper = new();
    private readonly PiperService _piper = new();
    private readonly PocketTtsService _pocket = new();
    private readonly VoiceConfig _config = new();
    private WakeWordDetector? _wakeWordDetector;
    private CancellationTokenSource? _speakCts;
    private StreamPlayer? _activePlayer;
    private string _ttsEngine = "piper";
    private string _voiceReferencePath = "";

    private readonly Dictionary<string, string> _personalityVoices = new()
    {
        ["Friendly"] = "ru_RU-ruslan-medium",
        ["Formal"] = "ru_RU-dmitri-medium",
        ["Sarcastic"] = "ru_RU-ruslan-medium",
        ["Professional"] = "ru_RU-dmitri-medium",
        ["Casual"] = "ru_RU-ruslan-medium"
    };

    public bool IsVoiceAvailable => _whisper.IsInstalled();
    public bool IsTtsAvailable => _pocket.IsAvailable || _piper.IsLoaded;
    public VoiceConfig Config => _config;

    /// <summary>
    /// Настройка движка озвучки ДО Initialize.
    /// engine: "pocket" — клонирование голоса (xVibePocketTTS, потоковый PCM),
    /// "piper" — классический синтез по предложениям.
    /// voiceReferencePath — WAV с образцом голоса пользователя (пусто = встроенный).
    /// </summary>
    public void ConfigureTts(string engine, string voiceReferencePath)
    {
        _ttsEngine = engine;
        _voiceReferencePath = voiceReferencePath;
    }

    public bool Initialize(string? personalityStyle = null)
    {
        var voiceName = _config.PiperVoice;

        if (personalityStyle != null &&
            _personalityVoices.TryGetValue(personalityStyle, out var styleVoice))
        {
            voiceName = styleVoice;
        }

        // Параметры инференса (скорость речи, пауза после предложения) —
        // до Initialize, чтобы процесс piper сразу стартовал с ними.
        _piper.SetInferenceParams(_config.SpeechSpeed, _config.SentenceSilence);

        var ttsReady = _piper.Initialize(voiceName);

        if (ttsReady)
        {
            Console.WriteLine($"[Voice] TTS готов. Голос: {_piper.CurrentVoice}");
        }
        else
        {
            Console.WriteLine("[Voice] TTS недоступен. Только текстовый режим.");
        }

        // Этап 2: клонирование голоса (PocketTTS); при сбое — откат на Piper.
        if (_ttsEngine.Equals("pocket", StringComparison.OrdinalIgnoreCase))
        {
            if (_pocket.Initialize(_voiceReferencePath))
            {
                Console.WriteLine("[Voice] Движок: PocketTTS (клонирование голоса, потоковый PCM).");
            }
            else
            {
                Console.WriteLine("[Voice] PocketTTS недоступен — используем Piper.");
            }
        }

        return ttsReady || _pocket.IsAvailable;
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
        if (!_pocket.IsAvailable && !_piper.IsLoaded)
        {
            Console.WriteLine($"[JARVIS] {text}");
            return;
        }

        // Новая речь прерывает текущую: отменяем цикл озвучки и сразу глушим
        // оба плеера, чтобы не ждать конца текущего предложения.
        _speakCts?.Cancel();
        _speakCts?.Dispose();
        _speakCts = new CancellationTokenSource();
        _player.Stop();
        _activePlayer?.Stop();
        var ct = _speakCts.Token;

        var spoken = 0;

        try
        {
            spoken = _pocket.IsAvailable
                ? await SpeakPocketAsync(text, ct)
                : await SpeakPiperAsync(text, ct);
        }
        catch (OperationCanceledException)
        {
            // Озвучка прервана — это нормальный сценарий.
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Voice] Ошибка озвучки: {ex.Message}");
        }

        // Фолбэк: TTS не выдал ни одного кадра (и это не отмена) — печатаем текст,
        // чтобы ответ не потерялся.
        if (spoken == 0 && !ct.IsCancellationRequested)
        {
            Console.WriteLine($"[JARVIS] {text}");
        }
    }

    /// <summary>
    /// Попредложенное воспроизведение через Piper: первое предложение играет,
    /// пока следующее ещё синтезируется. Здесь же применяется DSP-обработка.
    /// </summary>
    private async Task<int> SpeakPiperAsync(string text, CancellationToken ct)
    {
        var spoken = 0;

        await foreach (var wavFile in _piper.SynthesizeStreamAsync(text, ct))
        {
            if (ct.IsCancellationRequested)
            {
                TryDelete(wavFile);
                break;
            }

            string fileToPlay = wavFile;

            // Профессиональная DSP-обработка: EQ, компрессия, нормализация
            if (_config.AudioProcessing)
            {
                fileToPlay = AudioProcessor.Process(wavFile);
            }

            await _player.PlayAsync(fileToPlay, _config.Volume);

            TryDelete(fileToPlay);
            if (fileToPlay != wavFile)
                TryDelete(wavFile);

            spoken++;

            if (ct.IsCancellationRequested)
                break;
        }

        return spoken;
    }

    /// <summary>
    /// Потоковое воспроизведение через PocketTTS: PCM идёт кусками, плеер
    /// стартует на первых же сэмплах (~200–500 мс до звука), DSP здесь
    /// не применяется — поток не буферизуется целиком.
    /// </summary>
    private async Task<int> SpeakPocketAsync(string text, CancellationToken ct)
    {
        var player = new StreamPlayer(_pocket.SampleRate, _config.Volume);
        _activePlayer = player;

        try
        {
            var received = 0;

            await foreach (var chunk in _pocket.SynthesizePcmAsync(text, ct))
            {
                player.AddSamples(chunk, 0, chunk.Length);
                received += chunk.Length;
            }

            if (received == 0)
                return 0;

            player.Complete();
            await player.WaitUntilFinishedAsync(ct);
            return 1;
        }
        finally
        {
            _activePlayer = null;
            player.Dispose();
        }
    }

    private static void TryDelete(string? path)
    {
        if (string.IsNullOrEmpty(path))
            return;

        try { File.Delete(path); } catch { /* файл мог уже удалиться */ }
    }

    /// <summary>
    /// Записывает референс голоса для клонирования (10–30 секунд чистой речи)
    /// и сохраняет его в voice/reference.wav. Возвращает путь или null.
    /// </summary>
    public async Task<string?> RecordVoiceReferenceAsync(int seconds = 15)
    {
        try
        {
            var wav = await _recorder.RecordAsync(seconds, sampleRate: 24000);

            var dir = Path.Combine(Directory.GetCurrentDirectory(), "voice");
            Directory.CreateDirectory(dir);
            var target = Path.Combine(dir, "reference.wav");

            File.Copy(wav, target, overwrite: true);
            try { File.Delete(wav); } catch { }

            return Path.GetFullPath(target);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Voice] Не удалось записать референс: {ex.Message}");
            return null;
        }
    }

    public void StopSpeaking()
    {
        _speakCts?.Cancel();
        _player.Stop();
        _activePlayer?.Stop();
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
    /// Использует тот же ContinuousAudioRecorder что и детектор — без пересоздания.
    /// Ждёт речи, записывает, останавливается при тишине.
    /// </summary>
    public async Task<string> ListenCommandAsync()
    {
        if (!_whisper.IsInstalled())
        {
            Console.WriteLine("[Voice] Whisper не установлен.");
            return "";
        }

        // Используем рекордер из детектора (непрерывная запись)
        var recorder = _wakeWordDetector?.Recorder;

        if (recorder == null || !recorder.IsRecording)
        {
            // Fallback: используем обычный рекордер
            var wav = await _recorder.RecordWithVadAsync(maxSeconds: 10, silenceMs: 1500);

            if (string.IsNullOrEmpty(wav) || !File.Exists(wav))
                return "";

            var fileInfo = new FileInfo(wav);
            if (fileInfo.Length < 2000)
            {
                try { File.Delete(wav); } catch { }
                return "";
            }

            Console.WriteLine("🧠 Распознаю команду...");
            var result = await _whisper.TranscribeAsync(wav);
            try { File.Delete(wav); } catch { }
            return result;
        }

        // Ждём начала речи
        var waitStart = DateTime.Now;
        while (!recorder.IsSpeechDetected &&
               (DateTime.Now - waitStart).TotalSeconds < 8)
        {
            await Task.Delay(200);
        }

        if (!recorder.IsSpeechDetected)
        {
            Console.WriteLine("⚠️ Речь не обнаружена.");
            return "";
        }

        // Речь обнаружена — ждём окончания
        var lastSpeechTime = DateTime.Now;
        var speechStart = DateTime.Now;

        while ((DateTime.Now - lastSpeechTime).TotalMilliseconds < 1500 &&
               (DateTime.Now - speechStart).TotalSeconds < 10)
        {
            await Task.Delay(200);

            if (recorder.IsSpeechDetected)
                lastSpeechTime = DateTime.Now;
        }

        // Извлекаем аудио с буфером до речи
        var totalSeconds = (float)(DateTime.Now - speechStart).TotalSeconds + 1.5f;
        totalSeconds = Math.Min(totalSeconds, 12f);

        var audioBytes = recorder.ExtractRecentAudioBytes(totalSeconds);

        if (audioBytes.Length < 2000)
        {
            Console.WriteLine("⚠️ Запись слишком короткая.");
            return "";
        }

        // Сохраняем во временный файл
        var cmdFile = Path.Combine(
            Directory.GetCurrentDirectory(),
            "voice", "input",
            $"cmd_{DateTime.Now:yyyyMMdd_HHmmss}.wav");

        Directory.CreateDirectory(Path.GetDirectoryName(cmdFile)!);

        var sampleRate = 16000;
        var waveFormat = new NAudio.Wave.WaveFormat(sampleRate, 16, 1);
        using (var writer = new NAudio.Wave.WaveFileWriter(cmdFile, waveFormat))
        {
            writer.Write(audioBytes, 0, audioBytes.Length);
        }

        Console.WriteLine("🧠 Распознаю команду...");

        var cmdResult = await _whisper.TranscribeAsync(cmdFile);

        try { File.Delete(cmdFile); } catch { }

        return cmdResult;
    }

    #endregion

    public void Dispose()
    {
        _speakCts?.Cancel();
        _speakCts?.Dispose();
        _activePlayer?.Dispose();
        _pocket.Dispose();
        _piper.Dispose();
        _recorder.Dispose();
        _player.Dispose();
        _wakeWordDetector?.Dispose();
        GC.SuppressFinalize(this);
    }
}
