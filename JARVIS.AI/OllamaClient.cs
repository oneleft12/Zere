using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using JARVIS.AI.Models;

namespace JARVIS.AI;

public class OllamaClient : IDisposable
{
    private readonly HttpClient _httpClient;
    private readonly string _model;
    private string? _resolvedUrl;

    public OllamaClient(string model = "qwen3.5:2b", int timeoutMinutes = 10)
    {
        _model = model;
        _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(timeoutMinutes)
        };

        _resolvedUrl = OllamaUrlResolver.Resolve();

        if (_resolvedUrl != null)
        {
            if (!_resolvedUrl.EndsWith('/'))
                _resolvedUrl += "/";
            _httpClient.BaseAddress = new Uri(_resolvedUrl);
        }
    }

    public async Task<string> GenerateAsync(string prompt, string? systemPrompt = null, float? temperature = null)
    {
        if (_resolvedUrl == null)
            return "Ollama не найдена. Запустите Ollama и перезапустите JARVIS.";

        const int maxRetries = 2;

        for (int attempt = 0; ; attempt++)
        {
            try
            {
                var effectivePrompt = systemPrompt != null
                    ? $"{systemPrompt}\n\nПользователь: {prompt}"
                    : $"{SystemPrompt.Jarvis}\n\nПользователь: {prompt}";

                var request = new
                {
                    model = _model,
                    prompt = effectivePrompt,
                    stream = true,
                    options = temperature.HasValue
                        ? new { temperature = temperature.Value }
                        : null
                };

                var content = new StringContent(
                    JsonSerializer.Serialize(request),
                    Encoding.UTF8,
                    "application/json");

                var httpResponse = await _httpClient.PostAsync("/api/generate", content);
                httpResponse.EnsureSuccessStatusCode();

                var result = await ReadStreamAsync(httpResponse.Content);

                if (string.IsNullOrWhiteSpace(result))
                    Console.Error.WriteLine("[Ollama] Пустой ответ от модели.");

                return string.IsNullOrWhiteSpace(result)
                    ? "Нет ответа от модели."
                    : result.Trim();
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

    private static async Task<string> ReadStreamAsync(HttpContent content)
    {
        var sb = new StringBuilder();

        using var stream = await content.ReadAsStreamAsync();
        using var reader = new StreamReader(stream, Encoding.UTF8, detectEncodingFromByteOrderMarks: true, bufferSize: 8192, leaveOpen: true);

        while (!reader.EndOfStream)
        {
            var line = await reader.ReadLineAsync();

            if (string.IsNullOrEmpty(line))
                continue;

            try
            {
                var json = JsonSerializer.Deserialize<OllamaStreamChunk>(line);

                if (json != null)
                {
                    if (!string.IsNullOrEmpty(json.response))
                        sb.Append(json.response);

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
