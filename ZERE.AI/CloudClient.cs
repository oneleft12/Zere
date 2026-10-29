using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace ZERE.AI;

/// <summary>Результат проверки ключа (openapi: AiKeyTestResult).</summary>
public sealed record KeyTestResult(
    bool Ok,
    string Message,
    List<string> Models,
    string CheckedWith,
    string KeyMask);

/// <summary>
/// Облачный клиент: любой OpenAI-совместимый API (chat/completions + models).
///
/// Один клиент обслуживает все пресеты (OpenAI, DeepSeek, OpenRouter, Groq,
/// свой сервер): меняются только Base URL, модель и ключ.
///
/// Правила задачи:
/// — ключ передаётся только в заголовке Authorization и живёт на бэкенде;
/// — ключ не попадает в логи и в тексты ошибок (сообщения санитизируются);
/// — ошибки провайдера переводятся в понятные русские тексты.
///
/// Паритет с Python-редакцией (zere/ai/cloud_client.py).
/// </summary>
public sealed class CloudClient : IDisposable
{
    public const int DefaultTimeoutSeconds = 60;
    public const int TestTimeoutSeconds = 20;

    /// <summary>
    /// Клиент представляется своим именем (OpenCode Go просит не выглядеть
    /// безликой HTTP-библиотекой) и держит стабильный идентификатор сессии
    /// на процесс — по нему шлюз оптимизирует маршрутизацию и кэш промптов.
    /// </summary>
    private const string UserAgent = "ZERE/1.9.0";

    private const string SessionHeader = "x-opencode-session";

    private static readonly string SessionId = Guid.NewGuid().ToString("N");

    private readonly HttpClient _http;
    private readonly bool _ownsHttp;

    public CloudClient(HttpClient? http = null, int timeoutSeconds = DefaultTimeoutSeconds)
    {
        TimeoutSeconds = timeoutSeconds;

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

    public int TimeoutSeconds { get; }

    public static string NormalizeBaseUrl(string? baseUrl) =>
        (baseUrl ?? "").Trim().TrimEnd('/');

    /// <summary>GET /models — «рабочий запрос» для проверки ключа.</summary>
    public async Task<List<string>> ListModelsAsync(
        string baseUrl,
        string apiKey,
        CancellationToken cancellationToken = default,
        int? timeoutSeconds = null)
    {
        var url = $"{NormalizeBaseUrl(baseUrl)}/models";

        using var response = await SendAsync(
            HttpMethod.Get, url, apiKey, body: null,
            timeoutSeconds ?? TestTimeoutSeconds, cancellationToken);

        var text = await response.Content.ReadAsStringAsync(cancellationToken);

        if ((int)response.StatusCode >= 400)
            throw Classify(response.StatusCode, text, apiKey);

        var models = new List<string>();

        try
        {
            using var document = JsonDocument.Parse(text);

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
        }
        catch (JsonException)
        {
            // не-JSON ответ трактуем как «списка моделей нет»
        }

        return models;
    }

    /// <summary>
    /// Проверяет ключ рабочим запросом: сначала /models, затем минимальный
    /// POST /chat/completions (max_tokens=1). Ошибка — AiError.
    /// </summary>
    public async Task<KeyTestResult> TestKeyAsync(
        string baseUrl,
        string apiKey,
        string model,
        CancellationToken cancellationToken = default)
    {
        List<string> models = [];

        try
        {
            models = await ListModelsAsync(baseUrl, apiKey, cancellationToken);
        }
        catch (AiError ex) when (ex.Code is AiErrorCodes.KeyInvalid or AiErrorCodes.NoCredits or AiErrorCodes.RateLimit)
        {
            // 401/402/429 — окончательный приговор ключу, мини-запрос не нужен.
            throw;
        }
        catch (AiError)
        {
            // Прочие ответы (404/405 у части совместимых серверов, сеть)
            // не приговор: проверяем ключ минимальным запросом к чату.
        }

        // Одного списка моделей мало: у части шлюзов (например, OpenCode Go)
        // он публичный и отдаётся даже с неверным ключом, поэтому ключ всегда
        // подтверждаем мини-запросом к выбранной модели (max_tokens=1).
        try
        {
            await ChatProbeAsync(baseUrl, apiKey, model, cancellationToken);
        }
        catch (AiError ex) when (ex.Code == AiErrorCodes.Network && models.Count > 0)
        {
            // Сеть дала сбой на мини-запросе, но список моделей уже пришёл:
            // ключ и доступность подтверждены — сбой не приговор.
        }

        var message = $"Ключ рабочий — тестовый запрос к модели «{model}» прошёл.";

        if (models.Count > 0)
            message += $" Доступно моделей: {models.Count}.";

        return new KeyTestResult(
            true,
            message,
            models.Take(100).ToList(),
            "chat",
            AiSettings.MaskKey(apiKey));
    }

    private async Task ChatProbeAsync(
        string baseUrl,
        string apiKey,
        string model,
        CancellationToken cancellationToken)
    {
        var body = new
        {
            model,
            messages = new[] { new { role = "user", content = "ping" } },
            max_tokens = 1,
            temperature = 0,
            stream = false,
        };

        using var response = await SendAsync(
            HttpMethod.Post,
            $"{NormalizeBaseUrl(baseUrl)}/chat/completions",
            apiKey,
            body,
            TestTimeoutSeconds,
            cancellationToken);

        if ((int)response.StatusCode >= 400)
        {
            var text = await response.Content.ReadAsStringAsync(cancellationToken);
            throw Classify(response.StatusCode, text, apiKey);
        }
    }

    /// <summary>POST /chat/completions — ответ модели строкой.</summary>
    public async Task<string> GenerateAsync(
        string prompt,
        string? systemPrompt,
        string baseUrl,
        string apiKey,
        string model,
        float? temperature = null,
        int? maxTokens = null,
        CancellationToken cancellationToken = default)
    {
        var messages = new List<object>();

        if (!string.IsNullOrEmpty(systemPrompt))
            messages.Add(new { role = "system", content = systemPrompt });

        messages.Add(new { role = "user", content = prompt });

        // null-поля не отправляем: часть провайдеров отклоняет
        // «temperature»/«max_tokens» со значением null.
        var body = new Dictionary<string, object?>
        {
            ["model"] = model,
            ["messages"] = messages,
            ["stream"] = false,
        };

        if (temperature is not null)
            body["temperature"] = temperature.Value;

        if (maxTokens is not null)
            body["max_tokens"] = maxTokens.Value;

        var url = $"{NormalizeBaseUrl(baseUrl)}/chat/completions";

        HttpResponseMessage response;

        try
        {
            response = await SendAsync(
                HttpMethod.Post, url, apiKey, body, TimeoutSeconds, cancellationToken);
        }
        catch (TaskCanceledException)
        {
            throw new AiError(
                AiErrorCodes.Network,
                "Облачный API не ответил вовремя (таймаут).",
                504);
        }
        catch (HttpRequestException)
        {
            // Ключ в текст ошибки не попадает, но всё равно не логируем сырое.
            throw new AiError(AiErrorCodes.Network, AiErrorCodes.MessageNetwork, 502);
        }

        using (response)
        {
            var text = await response.Content.ReadAsStringAsync(cancellationToken);

            if ((int)response.StatusCode >= 400)
                throw Classify(response.StatusCode, text, apiKey);

            try
            {
                using var document = JsonDocument.Parse(text);

                if (document.RootElement.ValueKind != JsonValueKind.Object ||
                    !document.RootElement.TryGetProperty("choices", out var choices) ||
                    choices.ValueKind != JsonValueKind.Array ||
                    choices.GetArrayLength() == 0)
                {
                    throw new AiError(AiErrorCodes.EmptyAnswer, AiErrorCodes.MessageEmptyAnswer, 502);
                }

                var first = choices[0];
                string? content = null;

                if (first.ValueKind == JsonValueKind.Object &&
                    first.TryGetProperty("message", out var message) &&
                    message.ValueKind == JsonValueKind.Object &&
                    message.TryGetProperty("content", out var messageContent) &&
                    messageContent.ValueKind == JsonValueKind.String)
                {
                    content = messageContent.GetString();
                }
                else if (first.ValueKind == JsonValueKind.Object &&
                         first.TryGetProperty("text", out var legacyText) &&
                         legacyText.ValueKind == JsonValueKind.String)
                {
                    content = legacyText.GetString();
                }

                if (string.IsNullOrWhiteSpace(content))
                    throw new AiError(AiErrorCodes.EmptyAnswer, AiErrorCodes.MessageEmptyAnswer, 502);

                return content.Trim();
            }
            catch (JsonException)
            {
                throw new AiError(AiErrorCodes.ProviderError, AiErrorCodes.MessageProviderError, 502);
            }
        }
    }

    private async Task<HttpResponseMessage> SendAsync(
        HttpMethod method,
        string url,
        string apiKey,
        object? body,
        int timeoutSeconds,
        CancellationToken cancellationToken)
    {
        using var request = new HttpRequestMessage(method, url);

        request.Headers.TryAddWithoutValidation("User-Agent", UserAgent);

        if (!string.IsNullOrEmpty(apiKey))
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);

        // Шлюзу OpenCode нужен идентификатор сессии: без него теряется кэш
        // промптов, а трафик может выглядеть как анонимный.
        if (url.Contains("opencode.ai", StringComparison.Ordinal))
            request.Headers.TryAddWithoutValidation(SessionHeader, SessionId);

        if (body is not null)
        {
            request.Content = new StringContent(
                JsonSerializer.Serialize(body),
                Encoding.UTF8,
                "application/json");
        }

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));

        try
        {
            return await _http.SendAsync(
                request,
                HttpCompletionOption.ResponseContentRead,
                timeout.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new TaskCanceledException("Таймаут запроса к провайдеру.");
        }
    }

    /// <summary>HTTP-статус провайдера → понятная ошибка (требование 11).</summary>
    private static AiError Classify(HttpStatusCode status, string? body, string? apiKey)
    {
        var code = (int)status;
        var detail = ShortBody(body, apiKey);
        var lowered = (body ?? "").ToLowerInvariant();

        if (code is 401 or 403)
            return new AiError(AiErrorCodes.KeyInvalid, AiErrorCodes.MessageKeyInvalid, 400);

        if (code == 402)
            return new AiError(AiErrorCodes.NoCredits, AiErrorCodes.MessageNoCredits, 400);

        if (code == 429)
            return new AiError(AiErrorCodes.RateLimit, AiErrorCodes.MessageRateLimit, 429);

        if (code == 404 && (lowered.Contains("model") || lowered.Contains("not found")))
            return new AiError(AiErrorCodes.ModelUnavailable, AiErrorCodes.MessageModelUnavailable, 400);

        if (code == 400 &&
            (lowered.Contains("model_not_found") ||
             lowered.Contains("does not exist") ||
             lowered.Contains("unknown model") ||
             lowered.Contains("invalid model")))
        {
            return new AiError(AiErrorCodes.ModelUnavailable, AiErrorCodes.MessageModelUnavailable, 400);
        }

        if (code >= 500)
        {
            var message = $"{AiErrorCodes.MessageProviderError} (HTTP {code})";
            return new AiError(AiErrorCodes.ProviderError, detail.Length > 0 ? $"{message}: {detail}" : message, 502);
        }

        var generic = $"{AiErrorCodes.MessageProviderError} (HTTP {code})";
        return new AiError(
            AiErrorCodes.ProviderError,
            detail.Length > 0 ? $"{generic}: {detail}" : generic,
            400);
    }

    /// <summary>Короткое безопасное описание ответа провайдера (без ключа).</summary>
    private static string ShortBody(string? body, string? apiKey)
    {
        var text = SecretRedactor.Redact((body ?? "").Trim().Replace('\n', ' '));

        if (!string.IsNullOrEmpty(apiKey))
            text = text.Replace(apiKey, AiSettings.MaskKey(apiKey));

        return text.Length > 200 ? text[..200] : text;
    }

    public void Dispose()
    {
        if (_ownsHttp)
            _http.Dispose();
    }
}
