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
    private readonly SemaphoreSlim _recordGate = new(1, 1);
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

    /// <summary>
    /// Предзагрузка модели Whisper в память при старте (анализ S3):
    /// первая транскрибация не ждёт загрузку ggml-файла. Вызывается в фоне.
    /// </summary>
    public void PreloadWhisper()
    {
        try
        {
            _whisper.Preload();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Voice] Предзагрузка Whisper: {ex.Message}");
        }
    }

    public async Task<string> ListenAsync()
    {
        if (!_whisper.IsInstalled())
        {
            Console.WriteLine("[Voice] Whisper не установлен.");
            return "";
        }

        string wav;

        // Семафор записи: панель и консоль не должны писать микрофон
        // одновременно (анализ F4).
        await _recordGate.WaitAsync();

        try
        {
            // Ошибки микрофона не должны ронять приложение (анализ F1).
            wav = await _recorder.RecordAsync();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Voice] Ошибка записи: {ex.Message}. Переключаюсь на текстовый ввод.");
            return "";
        }
        finally
        {
            _recordGate.Release();
        }

        if (string.IsNullOrEmpty(wav) || !File.Exists(wav))
            return "";

        Console.WriteLine("Распознаю речь...");

        try
        {
            var text = await _whisper.TranscribeAsync(wav, timeoutSeconds: 30);
            return text;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Voice] Ошибка распознавания: {ex.Message}");
            return "";
        }
        finally
        {
            TryDelete(wav);
        }
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
        var firstAudioLogged = false;
        var sw = System.Diagnostics.Stopwatch.StartNew();

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

            if (!firstAudioLogged)
            {
                firstAudioLogged = true;
                Console.WriteLine($"[Perf] TTS first audio={sw.ElapsedMilliseconds} мс (piper)");
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
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var player = new StreamPlayer(_pocket.SampleRate, _config.Volume);
        _activePlayer = player;

        try
        {
            var received = 0;
            var firstAudioLogged = false;

            try
            {
                await foreach (var chunk in _pocket.SynthesizePcmAsync(text, ct))
                {
                    player.AddSamples(chunk, 0, chunk.Length);
                    received += chunk.Length;

                    if (!firstAudioLogged)
                    {
                        firstAudioLogged = true;
                        Console.WriteLine($"[Perf] TTS first audio={sw.ElapsedMilliseconds} мс (pocket)");
                    }
                }
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception ex)
            {
                // Анализ F2: сбой потока TTS не должен оставлять движок
                // «мертвым» до конца сессии — помечаем недоступным, запускаем
                // фоновое восстановление сервера и откатываемся на Piper
                // уже для этой же реплики.
                Console.WriteLine($"[Pocket] Сбой потока TTS: {ex.Message}");
                _pocket.MarkUnavailableAndRecover();

                if (_piper.IsLoaded)
                {
                    Console.WriteLine("[Voice] Откат на Piper для этой реплики.");
                    player.Stop();
                    return await SpeakPiperAsync(text, ct);
                }

                return received > 0 ? 1 : 0;
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
            string wav;

            // Семафор записи: референс не должен пересекаться с ListenAsync
            // панели/консоли (анализ F4).
            await _recordGate.WaitAsync();

            try
            {
                wav = await _recorder.RecordAsync(seconds, sampleRate: 24000);
            }
            finally
            {
                _recordGate.Release();
            }

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
    /// Детектор ОДИН на сессию (анализ S3): раньше новый создавался на каждом
    /// цикле — это означало повторную калибровку VAD и повторную загрузку
    /// модели Whisper на каждую команду.
    /// </summary>
    public WakeWordDetector EnableWakeWord()
    {
        if (_wakeWordDetector == null)
            _wakeWordDetector = new WakeWordDetector(_config, _whisper);

        return _wakeWordDetector;
    }

    /// <summary>
    /// Выключает wake word: останавливает непрерывную запись и освобождает
    /// детектор при выходе из голосового режима (общий Whisper не трогается).
    /// </summary>
    public void DisableWakeWord()
    {
        if (_wakeWordDetector == null)
            return;

        try
        {
            _wakeWordDetector.Recorder.StopContinuousRecording();
        }
        catch { /* рекордер уже остановлен */ }

        _wakeWordDetector.Dispose();
        _wakeWordDetector = null;
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
            string wav;

            await _recordGate.WaitAsync();

            try
            {
                // Ошибки микрофона не должны ронять приложение (анализ F1).
                wav = await _recorder.RecordWithVadAsync(
                    maxSeconds: 10, silenceMs: _config.CommandSilenceMs);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Voice] Ошибка записи: {ex.Message}.");
                return "";
            }
            finally
            {
                _recordGate.Release();
            }

            if (string.IsNullOrEmpty(wav) || !File.Exists(wav))
                return "";

            var fileInfo = new FileInfo(wav);
            if (fileInfo.Length < 2000)
            {
                try { File.Delete(wav); } catch { }
                return "";
            }

            Console.WriteLine("🧠 Распознаю команду...");

            string result;

            try
            {
                result = await _whisper.TranscribeAsync(wav, timeoutSeconds: 30);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Voice] Ошибка распознавания: {ex.Message}");
                result = "";
            }

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

        // Речь обнаружена — ждём окончания (пауза тишины — из конфига,
        // было жёсткие 1500 мс, анализ S4)
        var lastSpeechTime = DateTime.Now;
        var speechStart = DateTime.Now;
        var silenceMs = _config.CommandSilenceMs;

        while ((DateTime.Now - lastSpeechTime).TotalMilliseconds < silenceMs &&
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

        // Сохраняем во временный файл (уникальное имя — панель и консоль
        // могут записывать одновременно, анализ F4)
        var cmdFile = Path.Combine(
            Directory.GetCurrentDirectory(),
            "voice", "input",
            $"cmd_{DateTime.Now:yyyyMMdd_HHmmss_fff}_{Guid.NewGuid():N}.wav");

        Directory.CreateDirectory(Path.GetDirectoryName(cmdFile)!);

        var sampleRate = 16000;
        var waveFormat = new NAudio.Wave.WaveFormat(sampleRate, 16, 1);
        using (var writer = new NAudio.Wave.WaveFileWriter(cmdFile, waveFormat))
        {
            writer.Write(audioBytes, 0, audioBytes.Length);
        }

        Console.WriteLine("🧠 Распознаю команду...");

        string cmdResult;

        try
        {
            cmdResult = await _whisper.TranscribeAsync(cmdFile, timeoutSeconds: 30);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Voice] Ошибка распознавания: {ex.Message}");
            cmdResult = "";
        }

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
        _whisper.Dispose();
        _recordGate.Dispose();
        GC.SuppressFinalize(this);
    }
}
