using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using ZERE.Voice.Audio;

namespace ZERE.Voice.WakeWord;

/// <summary>
/// Стриминговый детектор ключевого слова (keyword spotting) — порт
/// Python-класса <c>zere/voice/wakeword/kws_detector.py</c>.
///
/// Зачем: docs/VOICE_PERF_STABILITY_ANALYSIS.md, S2. Прежний
/// <see cref="WakeWordDetector"/> — энергетический VAD плюс ПОЛНЫЙ STT на
/// каждый всплеск речи и сравнение строк: любая речь в комнате (ТВ, разговор)
/// запускала распознавание сегмента до 9 с, жгла CPU и давала ложные
/// срабатывания, а сегмент ещё и сохранялся на диск.
///
/// Здесь вместо ASR — крошечная ONNX-модель «окно 1 с → вероятность слова»
/// (~50–100 тыс. параметров, весь DSP внутри графа), обученная под одно слово:
///
///     аудио 16 кГц → кольцевой буфер → окно 1 с каждые 40 мс
///       → ONNX (log-mel + CNN) → вероятность
///       → сглаживание (N подряд ≥ порога) → cooldown → срабатывание
///
/// Контракт модели (обучает tools/wake_word/): вход <c>audio</c> float32
/// (batch, window_samples), выход <c>score</c> float32 (batch, 1);
/// рядом манифест <c>wake_&lt;слово&gt;.json</c>.
/// </summary>
public class KwsWakeWordDetector : IWakeDetector
{
    /// <summary>Имя движка для статуса панели.</summary>
    public const string EngineName = "onnx-kws";

    /// <summary>Во сколько раз опрос чаще шага инференса (40 мс → 20 мс).</summary>
    private const int PollDivisor = 2;

    /// <summary>Длина окна энергетической отсечки тишины (мс).</summary>
    private const int GateWindowMs = 300;

    private readonly object _ringLock = new();
    private readonly object _sessionLock = new();
    private readonly List<float> _recent = new();

    private readonly VoiceConfig _config;
    private readonly float[] _gateSilenceWindow = Array.Empty<float>();

    private RingBuffer _ring;
    private InferenceSession? _session;
    private long _scoredUntil;
    private long _cooldownUntilMs;
    private volatile bool _listening;
    private volatile bool _disposed;

    private readonly int _sampleRate;
    private readonly int _windowSamples;
    private readonly int _hopSamples;
    private readonly int _minConsecutive;
    private readonly string _inputName;
    private readonly string _outputName;
    private readonly float _threshold;
    private readonly int _cooldownMs;
    private readonly bool _energyGate;
    private readonly float _gateRms;
    private readonly bool _debug;

    /// <summary>Путь к ONNX-модели (для логов и статуса).</summary>
    public string ModelPath { get; }

    /// <summary>Последняя посчитанная вероятность (для отладки).</summary>
    public float LastScore { get; private set; }

    /// <inheritdoc />
    public string Engine => EngineName;

    /// <summary>Загружена ли ONNX-сессия (проверка после <see cref="Warmup"/>).</summary>
    public bool IsReady
    {
        get
        {
            lock (_sessionLock)
                return _session != null;
        }
    }

    /// <inheritdoc />
    public ContinuousAudioRecorder Recorder { get; }

    /// <summary>
    /// Создаёт детектор по манифесту рядом с моделью. Значения из
    /// <see cref="VoiceConfig"/> (0 — «не переопределять») имеют приоритет.
    /// </summary>
    public KwsWakeWordDetector(VoiceConfig config, string modelPath)
    {
        _config = config;
        ModelPath = modelPath;

        var manifest = LoadManifest(modelPath);

        _sampleRate = manifest.SampleRate > 0 ? manifest.SampleRate : 16000;
        _windowSamples = manifest.WindowSamples > 0 ? manifest.WindowSamples : 16000;
        _hopSamples = Math.Max(1, manifest.HopSamples > 0 ? manifest.HopSamples : 640);
        _inputName = string.IsNullOrEmpty(manifest.InputName) ? "audio" : manifest.InputName;
        _outputName = string.IsNullOrEmpty(manifest.OutputName) ? "score" : manifest.OutputName;

        _threshold = config.WakeThreshold > 0f
            ? config.WakeThreshold
            : manifest.Threshold > 0f ? manifest.Threshold : 0.7f;

        _minConsecutive = config.WakeMinConsecutive > 0
            ? config.WakeMinConsecutive
            : Math.Max(1, manifest.MinConsecutive);

        _cooldownMs = config.WakeCooldownMs > 0
            ? config.WakeCooldownMs
            : Math.Max(0, manifest.CooldownMs);

        _energyGate = config.WakeEnergyGate;
        _gateRms = config.WakeGateRms > 0f ? config.WakeGateRms : 0.0015f;
        _debug = Environment.GetEnvironmentVariable("ZERE_WAKE_DEBUG") is not (null or "" or "0" or "false");

        _gateSilenceWindow = new float[Math.Max(1, _sampleRate * GateWindowMs / 1000)];
        _ring = new RingBuffer(_windowSamples * 2);
        Recorder = new ContinuousAudioRecorder();
    }

    /// <summary>
    /// Создаёт сессию onnxruntime и прогоняет нулевое окно: первый инференс
    /// самый дорогой (инициализация графа ~50–200 мс).
    /// </summary>
    public void Warmup()
    {
        try
        {
            var session = EnsureSession();

            lock (_sessionLock)
                RunModel(session, new float[_windowSamples]);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"⚠️ Прогрев wake-модели не удался: {ex.Message}");
        }
    }

    /// <inheritdoc />
    public async Task<string> WaitForWakeWordAsync(CancellationToken ct = default)
    {
        var session = EnsureSession();
        var pollMs = Math.Max(10, (int)(_hopSamples * 1000.0 / _sampleRate / PollDivisor));

        Recorder.StartContinuousRecording(bufferSeconds: 10);

        // Свежий буфер на каждый цикл ожидания: в старом остался хвост
        // предыдущей команды (и он бы сразу дал ложное срабатывание).
        lock (_ringLock)
        {
            _ring = new RingBuffer(_windowSamples * 2);
            _scoredUntil = 0;
            _recent.Clear();
        }

        _listening = true;
        Recorder.AddListener(OnAudio);

        var word = string.IsNullOrEmpty(_config.WakeWord) ? "зере" : _config.WakeWord;
        var completed = false;

        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(pollMs, ct).ConfigureAwait(false);

                long written;

                lock (_ringLock)
                    written = _ring.Written;

                // Реальное время: если отстали — считаем только последнее окно,
                // а не догоняем очередь устаревших (иначе копится задержка).
                if (written - _scoredUntil < _hopSamples)
                    continue;

                _scoredUntil = written;

                var score = ScoreWindow(session);
                LastScore = score;

                if (_debug && score >= 0.3f)
                    Console.WriteLine($"🎚️ KWS: {score:F3}");

                var now = Environment.TickCount64;

                if (now < _cooldownUntilMs)
                    continue;

                _recent.Add(score);

                while (_recent.Count > _minConsecutive)
                    _recent.RemoveAt(0);

                if (_recent.Count >= _minConsecutive && _recent.TrueForAll(value => value >= _threshold))
                {
                    Console.WriteLine($"🔔 Обнаружено (KWS): \"{word}\" (score={score:F2})");
                    completed = true;
                    _cooldownUntilMs = now + _cooldownMs;
                    _recent.Clear();
                    return word;
                }
            }
        }
        catch (OperationCanceledException)
        {
            // Выключение режима — не ошибка (паритет с Python-детектором).
        }
        catch (Exception ex)
        {
            Console.WriteLine($"⚠️ Ошибка KWS-детектора: {ex.Message}");
        }
        finally
        {
            _listening = false;
            Recorder.RemoveListener(OnAudio);

            // При срабатывании запись продолжается: она нужна для команды.
            if (!completed)
                Recorder.StopContinuousRecording();
        }

        return string.Empty;
    }

    private void OnAudio(float[] samples)
    {
        if (!_listening || _disposed)
            return;

        lock (_ringLock)
            _ring.Write(samples);
    }

    private float ScoreWindow(InferenceSession session)
    {
        float[] window;

        lock (_ringLock)
            window = _ring.ReadLast(_windowSamples);

        if (window.Length < _windowSamples)
        {
            // Ещё не набрали окно (старт записи): дополняем нулями слева,
            // чтобы модель всегда получала ровно window_samples сэмплов.
            var padded = new float[_windowSamples];
            Array.Copy(window, 0, padded, _windowSamples - window.Length, window.Length);
            window = padded;
        }

        if (_energyGate)
        {
            var tailLength = Math.Min(_gateSilenceWindow.Length, window.Length);
            double sum = 0;

            for (int i = window.Length - tailLength; i < window.Length; i++)
                sum += window[i] * (double)window[i];

            var rms = tailLength > 0 ? Math.Sqrt(sum / tailLength) : 0.0;

            // RMS тишины ~0.0005, речи ~0.02–0.1: порог 0.0015 безопасен
            // и экономит инференс, пока в комнате тихо.
            if (rms < _gateRms)
                return 0f;
        }

        lock (_sessionLock)
            return RunModel(session, window);
    }

    private float RunModel(InferenceSession session, float[] window)
    {
        var tensor = new DenseTensor<float>(new[] { 1, window.Length });
        window.AsSpan().CopyTo(tensor.Buffer.Span);

        var inputs = new List<NamedOnnxValue>
        {
            NamedOnnxValue.CreateFromTensor(_inputName, tensor)
        };

        using var results = session.Run(inputs);

        var value = results[0].AsTensor<float>()[0];

        return Math.Clamp(value, 0f, 1f);
    }

    private InferenceSession EnsureSession()
    {
        lock (_sessionLock)
        {
            if (_session != null)
                return _session;

            var options = new SessionOptions
            {
                GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL,
                InterOpNumThreads = 1,
                IntraOpNumThreads = 1   // модель крошечная: 1 поток дешевле
            };

            _session = new InferenceSession(ModelPath, options);
            return _session;
        }
    }

    private static WakeManifest LoadManifest(string modelPath)
    {
        var path = Path.ChangeExtension(modelPath, ".json");

        if (!File.Exists(path))
            return new WakeManifest();

        try
        {
            var text = File.ReadAllText(path);

            return JsonSerializer.Deserialize<WakeManifest>(text) ?? new WakeManifest();
        }
        catch (Exception)
        {
            Console.WriteLine($"⚠️ Манифест модели битый ({path}) — беру дефолты");
            return new WakeManifest();
        }
    }

    /// <summary>Манифест модели: ключи snake_case, как пишет tools/wake_word.</summary>
    private sealed class WakeManifest
    {
        [JsonPropertyName("sample_rate")] public int SampleRate { get; set; } = 16000;
        [JsonPropertyName("window_samples")] public int WindowSamples { get; set; } = 16000;
        [JsonPropertyName("hop_samples")] public int HopSamples { get; set; } = 640;
        [JsonPropertyName("threshold")] public float Threshold { get; set; } = 0.7f;
        [JsonPropertyName("min_consecutive")] public int MinConsecutive { get; set; } = 2;
        [JsonPropertyName("cooldown_ms")] public int CooldownMs { get; set; } = 1800;
        [JsonPropertyName("input_name")] public string InputName { get; set; } = "audio";
        [JsonPropertyName("output_name")] public string OutputName { get; set; } = "score";
        [JsonPropertyName("word")] public string? Word { get; set; }
    }

    /// <summary>Кольцевой буфер float: пишем блоки, читаем последние N сэмплов.</summary>
    private sealed class RingBuffer
    {
        private readonly float[] _buffer;
        private readonly int _capacity;
        private int _writePos;

        public RingBuffer(int capacity)
        {
            _capacity = Math.Max(1, capacity);
            _buffer = new float[_capacity];
        }

        /// <summary>Сколько всего сэмплов записано (монотонный счётчик).</summary>
        public long Written { get; private set; }

        public void Write(float[] samples)
        {
            var count = samples.Length;

            if (count >= _capacity)
            {
                Array.Copy(samples, count - _capacity, _buffer, 0, _capacity);
                _writePos = 0;
                Written += count;
                return;
            }

            var space = _capacity - _writePos;
            var take = Math.Min(count, space);

            Array.Copy(samples, 0, _buffer, _writePos, take);

            if (count > take)
                Array.Copy(samples, take, _buffer, 0, count - take);

            // Позицию двигаем на ВЕСЬ блок (не только на первую часть): иначе
            // после записи «через край» буфер начинает читаться не по порядку.
            _writePos = (_writePos + count) % _capacity;
            Written += count;
        }

        public float[] ReadLast(int count)
        {
            var available = (int)Math.Min(Math.Min(count, Written), _capacity);

            if (available <= 0)
                return Array.Empty<float>();

            var result = new float[available];
            var readPos = (int)((_writePos - available + _capacity) % _capacity);
            var first = Math.Min(available, _capacity - readPos);

            Array.Copy(_buffer, readPos, result, 0, first);

            if (first < available)
                Array.Copy(_buffer, 0, result, first, available - first);

            return result;
        }
    }

    /// <inheritdoc />
    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;
        _listening = false;

        try
        {
            Recorder.RemoveListener(OnAudio);
        }
        catch
        {
            // рекордер мог быть уже закрыт
        }

        Recorder.Dispose();

        lock (_sessionLock)
        {
            _session?.Dispose();
            _session = null;
        }

        GC.SuppressFinalize(this);
    }
}
