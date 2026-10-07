using System.Net.Http.Json;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

namespace ZERE.AI;

/// <summary>Состояние локального сервера и список моделей.</summary>
public sealed record LocalProbe(
    string Server,
    string BaseUrl,
    string Api,
    List<string> Models,
    string Detail);

/// <summary>Событие загрузки модели (SSE /api/ai/local/pull).</summary>
public sealed record PullEvent(
    string Status,
    string? Detail = null,
    int? Completed = null,
    int? Total = null,
    double? Percent = null,
    string? Model = null,
    string? Code = null,
    string? Message = null);

/// <summary>Результат тестового запроса к локальной модели (openapi).</summary>
public sealed record LocalTestResult(bool Ok, string Message, string Server, List<string> Models);

/// <summary>Понятная инструкция по установке локальной модели.</summary>
public sealed record InstallHint(
    string Title,
    string[] Steps,
    string Command,
    string DownloadUrl,
    string Model);

/// <summary>
/// Локальная модель: Ollama или другой OpenAI-совместимый сервер.
///
/// Проверки (требование 7 задачи):
/// — запущен ли локальный сервер;
/// — какие модели доступны;
/// — проходит ли тестовый запрос.
///
/// Ollama-специфика (нативные /api/tags и /api/pull) включается, когда
/// сервер отвечает как Ollama: тогда доступна загрузка модели с прогрессом.
///
/// Паритет с Python-редакцией (zere/ai/local_model.py).
/// </summary>
public sealed class LocalModelService : IDisposable
{
    public const int DefaultTimeoutSeconds = 4;

    /// <summary>
    /// Дополнительные адреса локального сервера. host.docker.internal здесь
    /// намеренно нет: его DNS-резолв на машине без Docker занимает секунды,
    /// а панель опрашивает статус регулярно (в OllamaUrlResolver он остаётся
    /// для сценария docker).
    /// </summary>
    private static readonly string[] FallbackRoots =
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
    ];

    private readonly HttpClient _http;
    private readonly bool _ownsHttp;

    public LocalModelService(HttpClient? http = null)
    {
        if (http is null)
        {
            _http = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };
            _ownsHttp = true;
        }
        else
        {
            _http = http;
        }
    }

    public static string NormalizeBaseUrl(string? baseUrl) => (baseUrl ?? "").Trim().TrimEnd('/');

    /// <summary>«http://127.0.0.1:11434/v1» → «http://127.0.0.1:11434».</summary>
    public static string NativeRoot(string? baseUrl)
    {
        var root = NormalizeBaseUrl(baseUrl);

        return root.EndsWith("/v1", StringComparison.Ordinal)
            ? root[..^"/v1".Length]
            : root;
    }

    /// <summary>
    /// Есть ли модель среди локальных: сравнение строгое (имя + тег), иначе
    /// панель обещала бы скачивание уже существующей модели. Исключение —
    /// неявный тег: «qwen3.5» == «qwen3.5:latest».
    /// </summary>
    public static bool ModelInstalled(string? model, IEnumerable<string> models)
    {
        var target = (model ?? "").Trim().ToLowerInvariant();

        if (target.Length == 0)
            return false;

        foreach (var available in models)
        {
            var candidate = (available ?? "").Trim().ToLowerInvariant();

            if (candidate == target)
                return true;

            if (candidate == $"{target}:latest" || target == $"{candidate}:latest")
                return true;
        }

        return false;
    }

    private static bool IsLocalHost(string baseUrl)
    {
        try
        {
            var host = new Uri(NormalizeBaseUrl(baseUrl)).Host.ToLowerInvariant();
            return host is "127.0.0.1" or "localhost" or "::1" or "[::1]" or "host.docker.internal";
        }
        catch (UriFormatException)
        {
            return false;
        }
    }

    /// <summary>Ищет живой локальный сервер и список моделей.</summary>
    public async Task<LocalProbe> ProbeAsync(
        string baseUrl,
        bool extraRoots = false,
        CancellationToken cancellationToken = default)
    {
        var configured = NormalizeBaseUrl(baseUrl);
        var candidates = new List<string>();

        if (configured.Length > 0)
            candidates.Add(configured);

        // Стандартные адреса Ollama подставляем только для локального Base URL:
        // иначе недоступный удалённый сервер «нашёлся» бы на 127.0.0.1.
        if (extraRoots && (configured.Length == 0 || IsLocalHost(configured)))
        {
            foreach (var root in FallbackRoots)
            {
                var candidate = $"{root}/v1";

                if (!candidates.Contains(candidate, StringComparer.Ordinal))
                    candidates.Add(candidate);
            }
        }

        foreach (var candidate in candidates)
        {
            var probe = await ProbeOllamaAsync(candidate, cancellationToken)
                        ?? await ProbeOpenAiAsync(candidate, cancellationToken);

            if (probe is not null)
                return probe;
        }

        return new LocalProbe("down", configured, "", [], AiErrorCodes.MessageLocalServerDown);
    }

    private async Task<LocalProbe?> ProbeOllamaAsync(string baseUrl, CancellationToken cancellationToken)
    {
        var url = $"{NativeRoot(baseUrl)}/api/tags";

        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(DefaultTimeoutSeconds));

            using var response = await _http.GetAsync(url, timeout.Token);

            if (!response.IsSuccessStatusCode)
                return null;

            var text = await response.Content.ReadAsStringAsync(cancellationToken);
            using var document = JsonDocument.Parse(text);

            var models = new List<string>();

            if (document.RootElement.ValueKind == JsonValueKind.Object &&
                document.RootElement.TryGetProperty("models", out var raw) &&
                raw.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in raw.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.Object &&
                        item.TryGetProperty("name", out var name) &&
                        name.ValueKind == JsonValueKind.String)
                    {
                        models.Add(name.GetString()!);
                    }
                }
            }

            return new LocalProbe("up", $"{NativeRoot(baseUrl)}/v1", "ollama", models, "Ollama запущена.");
        }
        catch (Exception)
        {
            // нет сервера / не Ollama — пробуем OpenAI-совместимый вариант
            return null;
        }
    }

    private async Task<LocalProbe?> ProbeOpenAiAsync(string baseUrl, CancellationToken cancellationToken)
    {
        var url = $"{NormalizeBaseUrl(baseUrl)}/models";

        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(DefaultTimeoutSeconds));

            using var response = await _http.GetAsync(url, timeout.Token);

            if (!response.IsSuccessStatusCode)
                return null;

            var text = await response.Content.ReadAsStringAsync(cancellationToken);
            using var document = JsonDocument.Parse(text);

            var models = new List<string>();

            if (document.RootElement.ValueKind == JsonValueKind.Object &&
                document.RootElement.TryGetProperty("data", out var data) &&
                data.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in data.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.Object &&
                        item.TryGetProperty("id", out var id) &&
                        id.ValueKind == JsonValueKind.String)
                    {
                        models.Add(id.GetString()!);
                    }
                }
            }

            return new LocalProbe(
                "up",
                NormalizeBaseUrl(baseUrl),
                "openai",
                models,
                "Локальный сервер доступен (OpenAI-совместимый API).");
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>Минимальный запрос к локальной модели (max_tokens=1).</summary>
    public async Task<LocalTestResult> TestAsync(
        string baseUrl,
        string model,
        CancellationToken cancellationToken = default)
    {
        var probe = await ProbeAsync(baseUrl, extraRoots: true, cancellationToken);

        if (probe.Server != "up")
            throw new AiError(AiErrorCodes.LocalServerDown, AiErrorCodes.MessageLocalServerDown);

        if (!ModelInstalled(model, probe.Models))
        {
            throw new AiError(
                AiErrorCodes.LocalModelMissing,
                $"Локальная модель «{model}» не загружена. Скачайте её кнопкой «Скачать модель» " +
                $"или командой: ollama pull {model}");
        }

        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(DefaultTimeoutSeconds));

            using var response = await _http.PostAsJsonAsync(
                $"{probe.BaseUrl}/chat/completions",
                new
                {
                    model,
                    messages = new[] { new { role = "user", content = "ping" } },
                    max_tokens = 1,
                    temperature = 0,
                    stream = false,
                },
                timeout.Token);

            if ((int)response.StatusCode == 404)
                throw new AiError(AiErrorCodes.LocalModelMissing, AiErrorCodes.MessageLocalModelMissing);

            if ((int)response.StatusCode >= 400)
            {
                throw new AiError(
                    AiErrorCodes.ModelUnavailable,
                    $"{AiErrorCodes.MessageModelUnavailable} (HTTP {(int)response.StatusCode})");
            }
        }
        catch (AiError)
        {
            throw;
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or OperationCanceledException)
        {
            throw new AiError(AiErrorCodes.LocalServerDown, AiErrorCodes.MessageLocalServerDown);
        }

        return new LocalTestResult(true, $"Локальная модель «{model}» отвечает.", "up", probe.Models);
    }

    /// <summary>Поток прогресса `ollama pull`: progress / done / error.</summary>
    public async IAsyncEnumerable<PullEvent> PullAsync(
        string baseUrl,
        string model,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var probe = await ProbeAsync(baseUrl, extraRoots: true, cancellationToken);

        if (probe.Server != "up")
        {
            yield return new PullEvent("error", Code: AiErrorCodes.LocalServerDown,
                Message: AiErrorCodes.MessageLocalServerDown);
            yield break;
        }

        if (probe.Api != "ollama")
        {
            yield return new PullEvent(
                "error",
                Code: AiErrorCodes.PullUnsupported,
                Message: "Автозагрузка доступна только для Ollama. Загрузите модель средствами " +
                         "вашего сервера, затем повторите проверку.");
            yield break;
        }

        var root = NativeRoot(probe.BaseUrl);

        // yield нельзя использовать внутри catch — ошибку отправки запроса
        // запоминаем и отдаём событием ниже.
        HttpResponseMessage? response = null;
        string? sendError = null;

        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Post, $"{root}/api/pull")
            {
                Content = new StringContent(
                    JsonSerializer.Serialize(new { model, stream = true }),
                    Encoding.UTF8,
                    "application/json"),
            };

            response = await _http.SendAsync(
                request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or OperationCanceledException)
        {
            sendError = SecretRedactor.Redact(ex.Message);
        }

        if (response is null)
        {
            yield return new PullEvent("error", Code: AiErrorCodes.Network,
                Message: $"{AiErrorCodes.MessageNetwork}: {sendError}");
            yield break;
        }

        using (response)
        {
            if ((int)response.StatusCode >= 400)
            {
                yield return new PullEvent(
                    "error",
                    Code: AiErrorCodes.LocalModelMissing,
                    Message: $"Не удалось скачать модель «{model}» (HTTP {(int)response.StatusCode}).");
                yield break;
            }

            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
            using var reader = new StreamReader(stream, Encoding.UTF8);

            string? lastError = null;

            while (!reader.EndOfStream)
            {
                var line = await reader.ReadLineAsync(cancellationToken);

                if (string.IsNullOrWhiteSpace(line))
                    continue;

                JsonDocument document;

                try
                {
                    document = JsonDocument.Parse(line);
                }
                catch (JsonException)
                {
                    continue;
                }

                using (document)
                {
                    var element = document.RootElement;

                    if (element.ValueKind != JsonValueKind.Object)
                        continue;

                    if (element.TryGetProperty("error", out var error) &&
                        error.ValueKind == JsonValueKind.String)
                    {
                        lastError = error.GetString();
                        break;
                    }

                    string? detail = null;

                    if (element.TryGetProperty("status", out var status) &&
                        status.ValueKind == JsonValueKind.String)
                    {
                        detail = status.GetString();
                    }

                    int? completed = null;
                    int? total = null;

                    if (element.TryGetProperty("completed", out var completedElement) &&
                        completedElement.ValueKind == JsonValueKind.Number)
                    {
                        completed = completedElement.GetInt32();
                    }

                    if (element.TryGetProperty("total", out var totalElement) &&
                        totalElement.ValueKind == JsonValueKind.Number)
                    {
                        total = totalElement.GetInt32();
                    }

                    double? percent = null;

                    if (completed is not null && total is > 0)
                        percent = Math.Round(completed.Value * 100.0 / total.Value, 1);

                    yield return new PullEvent("pulling", detail, completed, total, percent);

                    if (detail == "success")
                        break;
                }
            }

            if (lastError is not null)
            {
                yield return new PullEvent(
                    "error",
                    Code: AiErrorCodes.LocalModelMissing,
                    Message: $"Ollama не смогла скачать модель: {lastError}");
                yield break;
            }
        }

        yield return new PullEvent("done", Model: model, Message: $"Модель «{model}» готова.");
    }

    /// <summary>Понятная инструкция и команда для загрузки локальной модели.</summary>
    public static InstallHint BuildInstallHint(string model) => new(
        "Локальная модель не найдена",
        [
            "1. Установите Ollama: https://ollama.com/download (или winget install Ollama.Ollama).",
            "2. Запустите сервер: ollama serve (обычно запускается сам после установки).",
            $"3. Скачайте лёгкую модель: ollama pull {model}.",
            "4. Вернитесь в панель и нажмите «Проверить локальную модель».",
        ],
        $"ollama pull {model}",
        "https://ollama.com/download",
        model);

    public void Dispose()
    {
        if (_ownsHttp)
            _http.Dispose();
    }
}
