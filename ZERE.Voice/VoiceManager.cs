using ZERE.Voice.Audio;
using ZERE.Voice.ChatTts;
using ZERE.Voice.Pocket;
using ZERE.Voice.Sherpa;
using ZERE.Voice.WakeWord;
using ZERE.Voice.Whisper;

namespace ZERE.Voice;

public class VoiceManager : IDisposable
{
    private readonly AudioRecorder _recorder = new();
    private readonly AudioPlayer _player = new();
    private readonly WhisperService _whisper = new();
    private readonly GigaAmService _gigaam = new();
    private readonly ChatTtsService _chattts = new();
    private readonly PocketTtsService _pocket = new();
    private readonly VoiceConfig _config = new();
    private readonly SemaphoreSlim _recordGate = new(1, 1);
    private WakeWordDetector? _wakeWordDetector;
    private CancellationTokenSource? _speakCts;
    private StreamPlayer? _activePlayer;
    private string _ttsEngine = "chattts";
    private string _voiceReferencePath = "";
    private string _sttEngine = "gigaam";
    private bool _chatttsInitialized;

    /// <summary>
    /// Профили голоса ChatTTS под стиль личности. У ChatTTS нет именованных
    /// голосов: профиль — детерминированное зерно эмбеддинга говорящего,
    /// поэтому один профиль всегда звучит одинаково.
    /// </summary>
    private readonly Dictionary<string, string> _personalityVoices = new()
    {
        ["Friendly"] = "zere-warm",
        ["Formal"] = "zere-strict",
        ["Sarcastic"] = "zere-ironic",
        ["Professional"] = "zere-business",
        ["Casual"] = "zere-casual"
    };

    public bool IsVoiceAvailable => ActiveStt.IsInstalled();

    /// <summary>
    /// Доступен ли TTS. После инициализации состояние перепроверяется дёшево
    /// (два File.Exists у ChatTtsService): uv/сайдкар могут появиться при
    /// работающем ZERE, и тогда озвучка работает без перезапуска. До Initialize
    /// (режим `--panel`) состояние не переспрашивается — панель обязана честно
    /// отдавать 503, пока голос не инициализирован.
    /// </summary>
    public bool IsTtsAvailable =>
        _pocket.IsAvailable || (_chatttsInitialized ? _chattts.RefreshAvailability() : _chattts.IsLoaded);

    /// <summary>Причина недоступности TTS для панели (пусто, если доступен).</summary>
    public string TtsUnavailableReason => _chattts.UnavailableReason;
    public VoiceConfig Config => _config;

    /// <summary>
    /// Активный STT-движок (роутинг gigaam→whisper, §5 отчёта STT):
    /// GigaAM, если он выбран и модель готова; иначе Whisper, если тот есть;
    /// иначе GigaAm (попытка достроить модель). Ленивая проверка на каждый
    /// вызов — после завершения скачивания модели выбор переключается сам.
    /// </summary>
    private ISttService ActiveStt
    {
        get
        {
            var wantGigaAm = _sttEngine.Equals("gigaam", StringComparison.OrdinalIgnoreCase);

            if (wantGigaAm && _gigaam.IsInstalled())
                return _gigaam;

            if (_whisper.IsInstalled())
                return _whisper;

            return _gigaam;
        }
    }

    /// <summary>
    /// Настройка движка распознавания ДО Initialize (паритет ConfigureTts).
    /// engine: "gigaam" — GigaAM-v3 (sherpa-onnx, основной),
    /// "whisper" — откат на Whisper (ggml).
    /// </summary>
    public void ConfigureStt(string engine)
    {
        _sttEngine = string.IsNullOrWhiteSpace(engine)
            ? "gigaam"
            : engine.Trim().ToLowerInvariant();
    }

    /// <summary>
    /// Настройка движка озвучки ДО Initialize.
    /// engine: "pocket" — клонирование голоса (xVibePocketTTS, потоковый PCM),
    /// "chattts" — нейросетевой синтез ChatTTS (попредложенно, замена Piper).
    /// voiceReferencePath — WAV с образцом голоса пользователя (пусто = встроенный).
    /// </summary>
    public void ConfigureTts(string engine, string voiceReferencePath)
    {
        _ttsEngine = engine;
        _voiceReferencePath = voiceReferencePath;
    }

    public bool Initialize(string? personalityStyle = null)
    {
        var voiceName = _config.ChatTtsVoice;

        if (personalityStyle != null &&
            _personalityVoices.TryGetValue(personalityStyle, out var styleVoice))
        {
            voiceName = styleVoice;
        }

        // Параметры инференса (темп речи, пауза после предложения) — до
        // Initialize; у ChatTTS они уходят в каждый запрос, перезапуск не нужен.
        _chattts.SetInferenceParams(_config.SpeechSpeed, _config.SentenceSilence);

        var ttsReady = _chattts.Initialize(voiceName);
        _chatttsInitialized = true;

        if (ttsReady)
        {
            Console.WriteLine($"[Voice] TTS готов. Голос: {_chattts.CurrentVoice}");
        }
        else
        {
            Console.WriteLine("[Voice] TTS недоступен. Только текстовый режим.");
        }

        // Этап 2: клонирование голоса (PocketTTS); при сбое — откат на ChatTTS.
        if (_ttsEngine.Equals("pocket", StringComparison.OrdinalIgnoreCase))
        {
            if (_pocket.Initialize(_voiceReferencePath))
            {
                Console.WriteLine("[Voice] Движок: PocketTTS (клонирование голоса, потоковый PCM).");
            }
            else
            {
                Console.WriteLine("[Voice] PocketTTS недоступен — используем ChatTTS.");
            }
        }

        return ttsReady || _pocket.IsAvailable;
    }

    public void SetPersonalityVoice(string style)
    {
        if (_personalityVoices.TryGetValue(style, out var voice))
        {
            _chattts.SetVoice(voice);
            Console.WriteLine($"[Voice] Голос изменён на: {voice} (стиль: {style})");
        }
    }

    /// <summary>
    /// Предзагрузка активного STT-движка при старте (анализ S3): первая
    /// транскрибация не ждёт загрузку модели. Для GigaAM при отсутствии
    /// модели здесь же выполняется разовое скачивание (163 МБ, SHA-256).
    /// Вызывается в фоне.
    /// </summary>
    public void PreloadStt()
    {
        try
        {
            if (_sttEngine.Equals("gigaam", StringComparison.OrdinalIgnoreCase))
            {
                // Предпочитаемый движок: скачиваем/греем GigaAM; если он не
                // поднялся — подстраховываемся Whisper, чтобы голос работал.
                if (!_gigaam.Preload() && _whisper.IsInstalled())
                    _whisper.Preload();
            }
            else
            {
                _whisper.Preload();
            }

            Console.WriteLine(
                $"[Voice] STT активен: {ActiveStt.CurrentModel} (запрошен движок: {_sttEngine}).");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"[Voice] Предзагрузка STT: {ex.Message}");
        }
    }

    /// <summary>
    /// Транскрибация через активный STT-движок с автоматическим откатом:
    /// сбой GigaAM уводит на Whisper — зеркало отката TTS-движков
    /// (pocket→chattts, §5 плана STT-исследования).
    /// </summary>
    private async Task<string> TranscribeSttAsync(string wavFile, int timeoutSeconds = 30)
    {
        var engine = ActiveStt;

        try
        {
            return await engine.TranscribeAsync(wavFile, timeoutSeconds);
        }
        catch (Exception ex) when (engine is not WhisperService && _whisper.IsInstalled())
        {
            Console.WriteLine(
                $"[Voice] STT ({engine.CurrentModel}) сбой: {ex.Message} — откат на Whisper.");
            return await _whisper.TranscribeAsync(wavFile, timeoutSeconds);
        }
    }

    public async Task<string> ListenAsync()
    {
        if (!ActiveStt.IsInstalled())
        {
            Console.WriteLine("[Voice] STT не установлен (нет ни GigaAM, ни Whisper).");
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
            var text = await TranscribeSttAsync(wav);
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
        if (!_pocket.IsAvailable && !_chattts.IsLoaded)
        {
            Console.WriteLine($"[ZERE] {text}");
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
                : await SpeakChatTtsAsync(text, ct);
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
            Console.WriteLine($"[ZERE] {text}");
        }
    }

    /// <summary>
    /// Попредложенное воспроизведение через ChatTTS: первое предложение играет,
    /// пока следующее ещё синтезируется. Здесь же применяется DSP-обработка.
    /// </summary>
    private async Task<int> SpeakChatTtsAsync(string text, CancellationToken ct)
    {
        var spoken = 0;
        var firstAudioLogged = false;
        var sw = System.Diagnostics.Stopwatch.StartNew();

        await foreach (var wavFile in _chattts.SynthesizeStreamAsync(text, ct))
        {
            if (ct.IsCancellationRequested)
            {
                TryDelete(wavFile);
                break;
            }

            string fileToPlay = wavFile;

            // Профессиональная DSP-обработка: ресемплинг под устройство, EQ,
            // компрессия, нормализация. Ресемплинг здесь обязателен: ChatTTS
            // отдаёт 24000 Гц, и если отдать их как есть, NAudio/WASAPI будет
            // конвертировать сам — своим слабым ресемплером, что и даёт
            // «металлический» призвук на выходе.
            if (_config.AudioProcessing)
            {
                fileToPlay = AudioProcessor.Process(wavFile, ResolveOutputSampleRate());
            }

            if (!firstAudioLogged)
            {
                firstAudioLogged = true;
                Console.WriteLine($"[Perf] TTS first audio={sw.ElapsedMilliseconds} мс (chattts)");
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
                // фоновое восстановление сервера и откатываемся на ChatTTS
                // уже для этой же реплики.
                Console.WriteLine($"[Pocket] Сбой потока TTS: {ex.Message}");
                _pocket.MarkUnavailableAndRecover();

                if (_chattts.IsLoaded)
                {
                    Console.WriteLine("[Voice] Откат на ChatTTS для этой реплики.");
                    player.Stop();
                    return await SpeakChatTtsAsync(text, ct);
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
    /// Частота устройства вывода по умолчанию — под неё ресемплится озвучка.
    ///
    /// Определяется через системный микшер (MMDeviceEnumerator/WASAPI): берётся
    /// MixFormat устройства по умолчанию. Если узнать не удалось, используется
    /// AudioProcessor.DefaultSampleRate (44100) — нативная частота большинства
    /// устройств; она заведомо лучше, чем отдать 22050 Гц, которые аудио-движок
    /// потом конвертирует сам своим слабым ресемплером.
    /// </summary>
    private static int ResolveOutputSampleRate()
    {
        try
        {
            using var enumerator = new NAudio.CoreAudioApi.MMDeviceEnumerator();
            using var device = enumerator.GetDefaultAudioEndpoint(
                NAudio.CoreAudioApi.DataFlow.Render,
                NAudio.CoreAudioApi.Role.Multimedia);

            var rate = device.AudioClient.MixFormat.SampleRate;

            if (rate > 0)
                return rate;
        }
        catch
        {
            // Устройство могло исчезнуть/смениться — дефолт надёжнее исключения.
        }

        return AudioProcessor.DefaultSampleRate;
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
        if (!ActiveStt.IsInstalled())
        {
            Console.WriteLine("[Voice] STT не установлен (нет ни GigaAM, ни Whisper).");
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
                result = await TranscribeSttAsync(wav);
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
            cmdResult = await TranscribeSttAsync(cmdFile);
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
        _chattts.Dispose();
        _recorder.Dispose();
        _player.Dispose();
        _wakeWordDetector?.Dispose();
        _whisper.Dispose();
        _gigaam.Dispose();
        _recordGate.Dispose();
        GC.SuppressFinalize(this);
    }
}
