using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using ZERE.AI.Models;

namespace ZERE.AI;

public class OllamaClient : IAiClient, IDisposable
{
    // Размер контекста: память (лимитирована ~1500 символов) + 5 последних
    // диалогов укладываются в 2048 токенов; меньше контекст — быстрее
    // и предсказуемее инференс (анализ S5).
    private const int NumContext = 2048;

    private readonly HttpClient _httpClient;
    private readonly string _model;
    private readonly int _keepAlive;
    private string? _resolvedUrl;

    public string? ResolvedUrl => _resolvedUrl;

    public OllamaClient(
        string model = "t-tech/T-lite-it-2.1:q4_K_M",
        int timeoutMinutes = 10,
        int keepAlive = -1,
        int timeoutSeconds = 60)
    {
        _model = model;
        _keepAlive = keepAlive;

        // Таймаут в секундах имеет приоритет (голосу 10 минут — недопустимо,
        // анализ S5); минуты остаются для обратной совместимости конфига.
        var timeout = timeoutSeconds > 0
            ? TimeSpan.FromSeconds(timeoutSeconds)
            : TimeSpan.FromMinutes(timeoutMinutes);

        _httpClient = new HttpClient
        {
            Timeout = timeout
        };

        _resolvedUrl = OllamaUrlResolver.Resolve();

        if (_resolvedUrl != null)
        {
            if (!_resolvedUrl.EndsWith('/'))
                _resolvedUrl += "/";
            _httpClient.BaseAddress = new Uri(_resolvedUrl);
        }
    }

    public async Task<string> GenerateAsync(
        string prompt,
        string? systemPrompt = null,
        float? temperature = null,
        int? maxTokens = null)
    {
        if (_resolvedUrl == null)
            return "Ollama не найдена. Запустите Ollama и перезапустите ZERE.";

        const int maxRetries = 2;

        for (int attempt = 0; ; attempt++)
        {
            var sw = Stopwatch.StartNew();
            long firstTokenMs = -1;

            try
            {
                // P1-2: system-промпт передаётся ТОЛЬКО полем system Ollama API,
                // prompt идёт как есть — раньше он дублировался (PromptBuilder
                // вставлял его в prompt, клиент дополнительно префиксовал).
                var options = BuildOptions(temperature, maxTokens);

                var request = new
                {
                    model = _model,
                    system = systemPrompt ?? SystemPrompt.Zere,
                    prompt,
                    stream = true,
                    keep_alive = _keepAlive,
                    // Русский язык и слабый ПК: thinking-трейс у reasoning-моделей
                    // (Qwen3.5, Gemma 4) уходит в рассуждения на английском и
                    // тратит сотни токенов — на CPU это десятки секунд на ответ.
                    think = false,
                    options
                };

                var content = new StringContent(
                    JsonSerializer.Serialize(request),
                    Encoding.UTF8,
                    "application/json");

                using var httpRequest = new HttpRequestMessage(HttpMethod.Post, "/api/generate")
                {
                    Content = content
                };

                // ResponseHeadersRead — без него HttpClient буферизует весь
                // NDJSON до чтения, и стриминг внутри клиента бессмысленен
                // (аудит P2-11).
                using var httpResponse = await _httpClient.SendAsync(
                    httpRequest, HttpCompletionOption.ResponseHeadersRead);

                httpResponse.EnsureSuccessStatusCode();

                var result = await ReadStreamAsync(httpResponse.Content, ms =>
                {
                    if (firstTokenMs < 0)
                        firstTokenMs = ms;
                });

                if (string.IsNullOrWhiteSpace(result))
                    Console.Error.WriteLine("[Ollama] Пустой ответ от модели.");

                var answer = string.IsNullOrWhiteSpace(result)
                    ? "Нет ответа от модели."
                    : result.Trim();

                Console.WriteLine(
                    $"[Perf] LLM first token={firstTokenMs} мс, total={sw.ElapsedMilliseconds} мс " +
                    $"(модель: {_model})");

                return answer;
            }
            catch (TaskCanceledException)
            {
                Console.Error.WriteLine($"[Ollama] Таймаут при генерации. Модель: '{_model}'");
                return $"Ollama не отвечает (таймаут). Проверьте модель '{_model}': ollama pull {_model}";
            }
            catch (HttpRequestException ex) when (attempt < maxRetries)
            {
                Console.Error.WriteLine($"[Ollama] HTTP ошибка (попытка {attempt + 1}/{maxRetries + 1}): {ex.Message}");
                await Task.Delay(1000);
                continue;
            }
            catch (HttpRequestException ex)
            {
                Console.Error.WriteLine($"[Ollama] Ошибка HTTP после {maxRetries + 1} попыток: {ex.Message}");
                return $"Не удалось подключиться к Ollama: {ex.Message}";
            }
            catch (InvalidOperationException ex)
            {
                Console.Error.WriteLine($"[Ollama] Неверное состояние запроса: {ex.Message}");
                return $"Ошибка AI: {ex.Message}";
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[Ollama] Непредвиденная ошибка: {ex.Message}");
                return $"Ошибка AI: {ex.Message}";
            }
        }
    }

    /// <summary>
    /// Прогрев модели при старте (анализ S5): первый «настоящий» запрос
    /// не платит за загрузку весов. Ошибки не критичны.
    /// </summary>
    public async Task WarmupAsync()
    {
        if (_resolvedUrl == null)
            return;

        try
        {
            var sw = Stopwatch.StartNew();

            var request = new
            {
                model = _model,
                prompt = "Готово.",
                stream = false,
                keep_alive = _keepAlive,
                think = false,
                options = new { num_predict = 1, num_ctx = NumContext }
            };

            using var content = new StringContent(
                JsonSerializer.Serialize(request), Encoding.UTF8, "application/json");

            using var response = await _httpClient.PostAsync("/api/generate", content);
            response.EnsureSuccessStatusCode();

            Console.WriteLine($"[Perf] LLM прогрев={sw.ElapsedMilliseconds} мс (модель: {_model})");
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[Ollama] Прогрев не удался (не критично): {ex.Message}");
        }
    }

    private static object BuildOptions(float? temperature, int? maxTokens)
    {
        // Анонимный объект с нужными полями: сериализатор пишет только
        // присутствующие свойства.
        if (temperature.HasValue && maxTokens.HasValue)
            return new { temperature = temperature.Value, num_predict = maxTokens.Value, num_ctx = NumContext };

        if (temperature.HasValue)
            return new { temperature = temperature.Value, num_ctx = NumContext };

        if (maxTokens.HasValue)
            return new { num_predict = maxTokens.Value, num_ctx = NumContext };

        return new { num_ctx = NumContext };
    }

    private static async Task<string> ReadStreamAsync(HttpContent content, Action<long>? onFirstChunk = null)
    {
        var sb = new StringBuilder();
        var sw = Stopwatch.StartNew();

        using var stream = await content.ReadAsStreamAsync();
        using var reader = new StreamReader(stream, Encoding.UTF8, detectEncodingFromByteOrderMarks: true, bufferSize: 8192, leaveOpen: true);

        while (true)
        {
            var line = await reader.ReadLineAsync();

            if (line is null)
                break;

            if (string.IsNullOrEmpty(line))
                continue;

            try
            {
                var json = JsonSerializer.Deserialize<OllamaStreamChunk>(line);

                if (json != null)
                {
                    if (!string.IsNullOrEmpty(json.response))
                    {
                        onFirstChunk?.Invoke(sw.ElapsedMilliseconds);
                        sb.Append(json.response);
                    }

                    if (json.done)
                        return sb.ToString();
                }
            }
            catch (JsonException)
            {
                // Skip malformed JSON
            }
        }

        return sb.ToString();
    }

    public void Dispose()
    {
        _httpClient.Dispose();
        GC.SuppressFinalize(this);
    }
}
