namespace ZERE.AI;

/// <summary>
/// Таймауты и keep_alive для локальной Ollama: ZERE.AI намеренно не зависит
/// от ZERE.Core (иначе циклическая ссылка проектов), поэтому вместо
/// ZereConfig сюда передаются только нужные значения.
/// </summary>
public sealed record AiTimeouts(
    int TimeoutSeconds = 60,
    int OllamaTimeoutMinutes = 10,
    int KeepAlive = -1);

/// <summary>Частичное обновление настроек ИИ (без ключа).</summary>
public sealed record AiSettingsUpdate(
    string? Mode = null,
    string? CloudProvider = null,
    string? CloudBaseUrl = null,
    string? CloudModel = null,
    string? LocalBaseUrl = null,
    string? LocalModel = null);

/// <summary>Проверка ключа рабочим запросом и сохранение.</summary>
public sealed record AiKeyRequest(
    string ApiKey,
    string? CloudProvider = null,
    string? CloudBaseUrl = null,
    string? CloudModel = null,
    bool Validate = true);

/// <summary>Проверка ключа без сохранения.</summary>
public sealed record AiKeyTestRequest(
    string? ApiKey = null,
    string? CloudProvider = null,
    string? CloudBaseUrl = null,
    string? CloudModel = null);

/// <summary>Тестовый запрос к локальной модели.</summary>
public sealed record AiLocalTestRequest(string? LocalBaseUrl = null, string? LocalModel = null);

/// <summary>
/// Сервис выбора провайдера ИИ: облачный ключ пользователя или локальная модель.
///
/// Собирает воедино настройки (AiSettings), облачный OpenAI-совместимый
/// клиент (CloudClient) и проверку локального сервера (LocalModelService),
/// а <see cref="AiProviderProxy"/> подставляется в AIHandler вместо
/// OllamaClient — интерфейс IAiClient сохранён, поэтому остальной код
/// (голос, консоль, панель) не меняется.
///
/// Приоритет (требование 5 задачи):
/// — auto: облачный ключ, если он есть; иначе локальная модель;
/// — cloud: только ключ;
/// — local: только локальная модель.
///
/// Паритет с Python-редакцией (zere/ai/ai_service.py).
/// </summary>
public sealed class AiService : IDisposable
{
    public const string ProviderCloud = "cloud";
    public const string ProviderLocal = "local";
    public const string ProviderNone = "none";

    /// <summary>Точная формулировка из задачи (требование 5).</summary>
    public const string MessageNotConfigured =
        "Чтобы начать, введите API-ключ или установите локальную модель";

    public const string MessageCloudKeyMissing =
        "Введите API-ключ облачной модели в настройках ИИ или переключитесь на локальную модель";

    public const string MessageKeyInvalidHint =
        "Неверный API-ключ. Проверьте ключ в настройках ИИ («Проверить ключ»).";

    public const string MessageLocalServerHint =
        "Локальный сервер не запущен. Установите и запустите Ollama: https://ollama.com/download";

    private const double ProbeCacheSeconds = 10.0;

    private readonly object _gate = new();
    private readonly AiTimeouts _timeouts;
    private readonly HttpClient _http;
    private readonly bool _ownsHttp;
    private readonly CloudClient _cloud;
    private readonly LocalModelService _local;

    private AiSettings _settings;

    private (DateTime At, string BaseUrl, bool ExtraRoots, LocalProbe Probe)? _probeCache;

    private OllamaClient? _localClient;
    private string _localClientModel = "";

    public AiService(AiTimeouts? timeouts = null, HttpClient? http = null)
    {
        _timeouts = timeouts ?? new AiTimeouts();

        if (http is null)
        {
            _http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
            _ownsHttp = true;
        }
        else
        {
            _http = http;
        }

        _settings = AiSettings.Load();
        _cloud = new CloudClient(_http, TimeoutSeconds());
        _local = new LocalModelService(_http);

        Proxy = new AiProviderProxy(this);
    }

    /// <summary>Прослойка для AIHandler: выбор провайдера на каждый запрос.</summary>
    public AiProviderProxy Proxy { get; }

    public AiSettings Settings
    {
        get
        {
            lock (_gate)
                return _settings;
        }
    }

    private int TimeoutSeconds()
    {
        var value = _timeouts.TimeoutSeconds;

        return value > 0 ? value : 60;
    }

    /// <summary>Перечитывает config/ai.json (например, после правки вручную).</summary>
    public void Reload()
    {
        lock (_gate)
        {
            _settings = AiSettings.Load();
            DisposeLocalClientLocked();
            _probeCache = null;
        }
    }

    // ── Проба локального сервера (с кэшем) ─────────────────────────

    public async Task<LocalProbe> LocalProbeAsync(
        bool force = false,
        bool extraRoots = false,
        CancellationToken cancellationToken = default)
    {
        string baseUrl;

        lock (_gate)
        {
            baseUrl = _settings.LocalBaseUrl;

            var cached = _probeCache;

            if (!force &&
                cached is not null &&
                cached.Value.BaseUrl == baseUrl &&
                cached.Value.ExtraRoots == extraRoots &&
                (DateTime.UtcNow - cached.Value.At).TotalSeconds < ProbeCacheSeconds)
            {
                return cached.Value.Probe;
            }
        }

        var probe = await _local.ProbeAsync(baseUrl, extraRoots, cancellationToken);

        lock (_gate)
            _probeCache = (DateTime.UtcNow, baseUrl, extraRoots, probe);

        return probe;
    }

    // ── Статус для панели (GET /api/ai) ───────────────────────────

    public async Task<object> StatusAsync(
        bool probeLocal = true,
        bool extraRoots = false,
        bool force = false,
        CancellationToken cancellationToken = default)
    {
        AiSettings settings;

        lock (_gate)
            settings = _settings;

        var cloud = settings.CloudPublic();
        var probe = probeLocal
            ? await LocalProbeAsync(force, extraRoots, cancellationToken)
            : new LocalProbe("unknown", settings.LocalBaseUrl, "", [], "");

        var local = BuildLocalPayload(settings, probe);
        var active = await ResolveProviderAsync(probe, cancellationToken);

        string summary;
        string message;
        bool ready;

        if (active == ProviderCloud)
        {
            summary = $"Подключено: облачная модель · {settings.CloudProvider}/{settings.CloudModel}";
            ready = true;
            message = "Запросы идут в облачную модель.";
        }
        else if (active == ProviderLocal)
        {
            summary = $"Подключено: локальная модель · {settings.LocalModel}";
            ready = true;
            message = "Запросы идут в локальную модель.";
        }
        else
        {
            summary = "Подключите API-ключ или используйте локальную модель";
            ready = false;
            message = MessageNotConfigured;
        }

        return new
        {
            mode = settings.Mode,
            activeProvider = active,
            ready,
            summary,
            message,
            cloud,
            local,
            presets = AiSettings.Presets,
            settingsPath = AiSettings.DescribePath(),
        };
    }

    /// <summary>Публичное состояние локальной модели (openapi: AiLocalStatus).</summary>
    private static object BuildLocalPayload(AiSettings settings, LocalProbe probe)
    {
        var model = settings.LocalModel;
        var installed = LocalModelService.ModelInstalled(model, probe.Models);
        var serverUp = probe.Server == "up";
        var canPull = serverUp && probe.Api == "ollama";

        string status;
        string statusText;

        if (serverUp && installed)
        {
            status = "available";
            statusText = "Локальная модель доступна";
        }
        else if (serverUp)
        {
            status = "model-missing";
            statusText = "Локальная модель недоступна";
        }
        else
        {
            status = "server-down";
            statusText = AiErrorCodes.MessageLocalServerDown;
        }

        object? installHint = serverUp && installed
            ? null
            : LocalModelService.BuildInstallHint(model);

        return new
        {
            baseUrl = settings.LocalBaseUrl,
            model,
            suggestions = AiSettings.LocalModelSuggestions,
            server = serverUp ? "up" : "down",
            api = probe.Api,
            resolvedBaseUrl = string.IsNullOrEmpty(probe.BaseUrl) ? settings.LocalBaseUrl : probe.BaseUrl,
            models = probe.Models,
            modelInstalled = installed,
            status,
            statusText,
            detail = probe.Detail,
            canPull,
            installHint,
        };
    }

    /// <summary>Какой провайдер будет использован прямо сейчас.</summary>
    public async Task<string> ResolveProviderAsync(
        LocalProbe? knownProbe = null,
        CancellationToken cancellationToken = default)
    {
        AiSettings settings;

        lock (_gate)
            settings = _settings;

        var mode = settings.Mode;
        var cloudReady = settings.HasKey();

        if (mode == AiSettings.ModeCloud)
            return cloudReady ? ProviderCloud : ProviderNone;

        if (mode == AiSettings.ModeLocal)
            return await LocalReadyAsync(knownProbe, cancellationToken) ? ProviderLocal : ProviderNone;

        if (cloudReady && settings.HasWorkingKey())
            return ProviderCloud;

        if (await LocalReadyAsync(knownProbe, cancellationToken))
            return ProviderLocal;

        return ProviderNone;
    }

    private async Task<bool> LocalReadyAsync(
        LocalProbe? knownProbe = null,
        CancellationToken cancellationToken = default)
    {
        LocalProbe probe;

        lock (_gate)
            probe = knownProbe ?? new LocalProbe("", _settings.LocalBaseUrl, "", [], "");

        if (knownProbe is null)
            probe = await LocalProbeAsync(cancellationToken: cancellationToken);

        if (probe.Server != "up")
            return false;

        string model;

        lock (_gate)
            model = _settings.LocalModel;

        return LocalModelService.ModelInstalled(model, probe.Models);
    }

    // ── Правка настроек ──────────────────────────────────────────

    public async Task<object> UpdateSettingsAsync(
        AiSettingsUpdate update,
        CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            if (update.Mode is not null)
            {
                if (!AiSettings.Modes.Contains(update.Mode, StringComparer.Ordinal))
                {
                    throw new AiError(
                        AiErrorCodes.Validation,
                        $"Режим «{update.Mode}» не поддерживается: {string.Join(", ", AiSettings.Modes)}.");
                }

                _settings.Mode = update.Mode;
            }

            if (update.CloudProvider is not null)
                _settings.CloudProvider = update.CloudProvider;

            if (update.CloudBaseUrl is not null)
                _settings.CloudBaseUrl = update.CloudBaseUrl.Trim();

            if (update.CloudModel is not null)
                _settings.CloudModel = update.CloudModel.Trim();

            if (update.LocalBaseUrl is not null)
                _settings.LocalBaseUrl = update.LocalBaseUrl.Trim();

            if (update.LocalModel is not null)
                _settings.LocalModel = update.LocalModel.Trim();

            _settings.Save();
            DisposeLocalClientLocked();
            _probeCache = null;
        }

        return await StatusAsync(cancellationToken: cancellationToken);
    }

    /// <summary>Сохраняет ключ, предварительно проверив его рабочим запросом.</summary>
    public async Task<object> SaveKeyAsync(AiKeyRequest request, CancellationToken cancellationToken = default)
    {
        var apiKey = (request.ApiKey ?? "").Trim();

        if (apiKey.Length == 0)
            throw new AiError(AiErrorCodes.Validation, "Введите API-ключ.");

        string baseUrl;
        string model;

        lock (_gate)
        {
            if (request.CloudProvider is not null)
                _settings.CloudProvider = request.CloudProvider;

            if (request.CloudBaseUrl is not null)
                _settings.CloudBaseUrl = request.CloudBaseUrl.Trim();

            if (request.CloudModel is not null)
                _settings.CloudModel = request.CloudModel.Trim();

            baseUrl = _settings.CloudBaseUrl;
            model = _settings.CloudModel;
        }

        if (request.Validate)
            await VerifyKeyAsync(apiKey, baseUrl, model, cancellationToken);

        lock (_gate)
        {
            _settings.CloudApiKey = apiKey;
            _settings.CloudKeyStatus = AiSettings.KeyOk;
            _settings.CloudKeyCheckedAt = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
            _settings.Save();
        }

        return await StatusAsync(cancellationToken: cancellationToken);
    }

    /// <summary>Проверка ключа без сохранения (кнопка «Проверить ключ»).</summary>
    public async Task<KeyTestResult> TestKeyAsync(
        AiKeyTestRequest request,
        CancellationToken cancellationToken = default)
    {
        string apiKey;
        string baseUrl;
        string model;
        var provided = !string.IsNullOrEmpty(request.ApiKey);

        lock (_gate)
        {
            baseUrl = (request.CloudBaseUrl ?? _settings.CloudBaseUrl).Trim();
            model = (request.CloudModel ?? _settings.CloudModel).Trim();

            if (provided)
            {
                apiKey = request.ApiKey!.Trim();
            }
            else
            {
                apiKey = _settings.ActiveKey().Key;

                if (apiKey.Length == 0)
                    throw new AiError(AiErrorCodes.Validation, "Сначала введите API-ключ.");
            }
        }

        var result = await VerifyKeyAsync(apiKey, baseUrl, model, cancellationToken);

        // Помечаем состояние ключа, только если проверялся сохранённый ключ:
        // введённый «на пробу» в файл не пишется и статус не меняет.
        if (!provided)
        {
            lock (_gate)
            {
                if (_settings.CloudApiKey == apiKey)
                {
                    _settings.CloudKeyStatus = AiSettings.KeyOk;
                    _settings.CloudKeyCheckedAt = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
                    _settings.Save();
                }
            }
        }

        return result;
    }

    private async Task<KeyTestResult> VerifyKeyAsync(
        string apiKey,
        string baseUrl,
        string model,
        CancellationToken cancellationToken)
    {
        try
        {
            return await _cloud.TestKeyAsync(baseUrl, apiKey, model, cancellationToken);
        }
        catch (AiError ex)
        {
            Console.Error.WriteLine($"[AI] проверка ключа ({AiSettings.MaskKey(apiKey)}) не прошла: {ex.Code}");

            if (ex.Code == AiErrorCodes.KeyInvalid)
            {
                lock (_gate)
                {
                    if (_settings.CloudApiKey == apiKey)
                    {
                        _settings.CloudKeyStatus = AiSettings.KeyInvalid;
                        _settings.CloudKeyCheckedAt = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
                        _settings.Save();
                    }
                }
            }

            throw;
        }
    }

    /// <summary>Удаляет ключ пользователя (ключ владельца из окружения не трогаем).</summary>
    public async Task<object> DeleteKeyAsync(CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            _settings.CloudApiKey = "";
            _settings.CloudKeyStatus = AiSettings.KeyUnknown;
            _settings.CloudKeyCheckedAt = "";
            _settings.Save();
        }

        return await StatusAsync(probeLocal: false, cancellationToken: cancellationToken);
    }

    // ── Локальная модель: статус, тест, загрузка ─────────────────

    public async Task<object> LocalStatusAsync(CancellationToken cancellationToken = default)
    {
        AiSettings settings;

        lock (_gate)
            settings = _settings;

        var probe = await LocalProbeAsync(force: true, extraRoots: true, cancellationToken: cancellationToken);

        return BuildLocalPayload(settings, probe);
    }

    public async Task<LocalTestResult> TestLocalAsync(
        AiLocalTestRequest request,
        CancellationToken cancellationToken = default)
    {
        string baseUrl;
        string model;

        lock (_gate)
        {
            baseUrl = (request.LocalBaseUrl ?? _settings.LocalBaseUrl).Trim();
            model = (request.LocalModel ?? _settings.LocalModel).Trim();
        }

        try
        {
            return await _local.TestAsync(baseUrl, model, cancellationToken);
        }
        finally
        {
            lock (_gate)
                _probeCache = null;
        }
    }

    public async IAsyncEnumerable<PullEvent> PullAsync(
        string? model = null,
        [System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        string target;
        string baseUrl;

        lock (_gate)
        {
            target = string.IsNullOrWhiteSpace(model) ? _settings.LocalModel : model!.Trim();
            baseUrl = _settings.LocalBaseUrl;
        }

        await foreach (var evt in _local.PullAsync(baseUrl, target, cancellationToken))
        {
            if (evt.Status is "done" or "error")
            {
                lock (_gate)
                {
                    _probeCache = null;
                    DisposeLocalClientLocked();
                }
            }

            yield return evt;
        }
    }

    // ── Генерация ────────────────────────────────────────────────

    public async Task<string> GenerateAsync(
        string prompt,
        string? systemPrompt = null,
        float? temperature = null,
        int? maxTokens = null,
        CancellationToken cancellationToken = default)
    {
        var provider = await ResolveProviderAsync(cancellationToken: cancellationToken);

        if (provider == ProviderCloud)
        {
            try
            {
                return await GenerateCloudAsync(prompt, systemPrompt, temperature, maxTokens, cancellationToken);
            }
            catch (AiError ex)
            {
                Console.Error.WriteLine($"[AI] облако: {ex.Code}");

                AiSettings settings;

                lock (_gate)
                    settings = _settings;

                // auto: облако упало — если есть локальная модель, отвечаем ею.
                if (settings.Mode == AiSettings.ModeAuto && await LocalReadyAsync(cancellationToken: cancellationToken))
                {
                    var local = await TryLocalAsync(prompt, systemPrompt, temperature, maxTokens, cancellationToken);

                    if (local is not null)
                        return local;
                }

                return ErrorText(ex);
            }
        }

        if (provider == ProviderLocal)
        {
            var local = await TryLocalAsync(prompt, systemPrompt, temperature, maxTokens, cancellationToken);

            return local ?? MessageLocalServerHint;
        }

        return await NoProviderTextAsync(cancellationToken);
    }

    private async Task<string> GenerateCloudAsync(
        string prompt,
        string? systemPrompt,
        float? temperature,
        int? maxTokens,
        CancellationToken cancellationToken)
    {
        string apiKey;
        string baseUrl;
        string model;

        lock (_gate)
        {
            (apiKey, _) = _settings.ActiveKey();
            baseUrl = _settings.CloudBaseUrl;
            model = _settings.CloudModel;
        }

        if (apiKey.Length == 0)
            throw new AiError("AI_KEY_MISSING", MessageCloudKeyMissing);

        return await _cloud.GenerateAsync(
            prompt, systemPrompt, baseUrl, apiKey, model, temperature, maxTokens, cancellationToken);
    }

    /// <summary>Локальная генерация; null — провайдер недоступен.</summary>
    private async Task<string?> TryLocalAsync(
        string prompt,
        string? systemPrompt,
        float? temperature,
        int? maxTokens,
        CancellationToken cancellationToken)
    {
        var probe = await LocalProbeAsync(cancellationToken: cancellationToken);

        if (probe.Server != "up")
            return null;

        string model;

        lock (_gate)
            model = _settings.LocalModel;

        if (!LocalModelService.ModelInstalled(model, probe.Models))
            return null;

        try
        {
            if (probe.Api == "openai")
            {
                try
                {
                    return await _cloud.GenerateAsync(
                        prompt, systemPrompt, probe.BaseUrl, "", model, temperature, maxTokens, cancellationToken);
                }
                catch (AiError ex)
                {
                    Console.Error.WriteLine($"[AI] локально (openai): {ex.Code}");

                    if (ex.Code == AiErrorCodes.ModelUnavailable)
                    {
                        return $"{AiErrorCodes.MessageLocalModelMissing}. Скачайте модель «{model}» " +
                               "средствами вашего локального сервера.";
                    }

                    return $"{AiErrorCodes.MessageLocalServerDown} или не отвечает ({probe.BaseUrl}).";
                }
            }

            var client = LocalOllamaClient(model);
            return await client.GenerateAsync(prompt, systemPrompt, temperature, maxTokens);
        }
        catch (AiError ex)
        {
            Console.Error.WriteLine($"[AI] локально: {ex.Code}");
            return ErrorText(ex);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[AI] локально: {SecretRedactor.Redact(ex.Message)}");
            return MessageLocalServerHint;
        }
    }

    private OllamaClient LocalOllamaClient(string model)
    {
        lock (_gate)
        {
            if (_localClient is not null && _localClientModel == model)
                return _localClient;

            DisposeLocalClientLocked();

            _localClient = new OllamaClient(
                model,
                _timeouts.OllamaTimeoutMinutes,
                _timeouts.KeepAlive,
                TimeoutSeconds());
            _localClientModel = model;

            return _localClient;
        }
    }

    private void DisposeLocalClientLocked()
    {
        try
        {
            _localClient?.Dispose();
        }
        catch (Exception)
        {
            // закрытие best-effort
        }

        _localClient = null;
        _localClientModel = "";
    }

    // ── Тексты ошибок (требование 11) ────────────────────────────

    private string ErrorText(AiError error) => error.Code switch
    {
        AiErrorCodes.KeyInvalid => MessageKeyInvalidHint,
        AiErrorCodes.LocalServerDown => MessageLocalServerHint,
        AiErrorCodes.LocalModelMissing => LocalMissingText(),
        _ => error.Message,
    };

    private string LocalMissingText()
    {
        string model;

        lock (_gate)
            model = _settings.LocalModel;

        return $"{AiErrorCodes.MessageLocalModelMissing}. Скачайте её в панели «Скачать модель» " +
               $"или командой: ollama pull {model}";
    }

    private async Task<string> NoProviderTextAsync(CancellationToken cancellationToken)
    {
        AiSettings settings;

        lock (_gate)
            settings = _settings;

        var key = settings.HasKey();
        var keyStatus = settings.CloudKeyStatus;

        if (key && keyStatus == AiSettings.KeyInvalid)
            return MessageKeyInvalidHint;

        if (settings.Mode == AiSettings.ModeLocal)
        {
            var probe = await LocalProbeAsync(cancellationToken: cancellationToken);

            if (probe.Server != "up")
                return MessageLocalServerHint;

            return LocalMissingText();
        }

        return MessageNotConfigured;
    }

    // ── Совместимость с OllamaClient ─────────────────────────────

    public async Task WarmupAsync()
    {
        if (await ResolveProviderAsync() != ProviderLocal)
            return;

        try
        {
            var probe = await LocalProbeAsync();

            if (probe.Api != "ollama")
                return;

            string model;

            lock (_gate)
                model = _settings.LocalModel;

            await LocalOllamaClient(model).WarmupAsync();
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[AI] прогрев: {SecretRedactor.Redact(ex.Message)}");
        }
    }

    public void Dispose()
    {
        lock (_gate)
            DisposeLocalClientLocked();

        _cloud.Dispose();
        _local.Dispose();

        if (_ownsHttp)
            _http.Dispose();
    }
}

/// <summary>
/// Прослойка в AIHandler: интерфейс IAiClient, выбор провайдера на лету.
/// Панель меняет настройки ИИ без перезапуска ZERE.
/// </summary>
public sealed class AiProviderProxy : IAiClient
{
    private readonly AiService _service;

    public AiProviderProxy(AiService service)
    {
        _service = service;
    }

    public AiService Service => _service;

    public Task<string> GenerateAsync(
        string prompt,
        string? systemPrompt = null,
        float? temperature = null,
        int? maxTokens = null)
    {
        return _service.GenerateAsync(prompt, systemPrompt, temperature, maxTokens);
    }

    public Task WarmupAsync() => _service.WarmupAsync();
}
