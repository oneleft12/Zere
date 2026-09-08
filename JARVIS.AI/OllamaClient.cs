using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using JARVIS.AI.Models;

namespace JARVIS.AI;

public class OllamaClient
{
    private readonly HttpClient _httpClient;
    private readonly string _model;
    private string? _resolvedUrl;

    private static readonly string[] Candidates =
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://host.docker.internal:11434"
    ];

    public OllamaClient(string model = "qwen3.5:2b", int timeoutMinutes = 10)
    {
        _model = model;
        _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(timeoutMinutes)
        };

        _resolvedUrl = ResolveOllamaUrl();

        if (_resolvedUrl != null)
            _httpClient.BaseAddress = new Uri(_resolvedUrl);
    }

    public async Task<string> GenerateAsync(string prompt)
    {
        if (_resolvedUrl == null)
            return "Ollama не найдена. Запустите Ollama и перезапустите JARVIS.";

        try
        {
            var request = new
            {
                model = _model,
                prompt = $"{SystemPrompt.Jarvis}\n\nПользователь: {prompt}",
                stream = true
            };

            var content = new StringContent(
                JsonSerializer.Serialize(request),
                Encoding.UTF8,
                "application/json");

            var httpResponse = await _httpClient.PostAsync("/api/generate", content);
            httpResponse.EnsureSuccessStatusCode();

            var result = await ReadStreamAsync(httpResponse.Content);

            return string.IsNullOrWhiteSpace(result)
                ? "Нет ответа от модели."
                : result.Trim();
        }
        catch (TaskCanceledException)
        {
            return $"Ollama не отвечает (таймаут). Проверьте модель '{_model}': ollama pull {_model}";
        }
        catch (HttpRequestException ex)
        {
            return $"Не удалось подключиться к Ollama: {ex.Message}";
        }
        catch (Exception ex)
        {
            return $"Ошибка AI: {ex.Message}";
        }
    }

    private static async Task<string> ReadStreamAsync(HttpContent content)
    {
        var sb = new StringBuilder();

        using var stream = await content.ReadAsStreamAsync();
        using var reader = new StreamReader(stream);

        while (!reader.EndOfStream)
        {
            var line = await reader.ReadLineAsync();

            if (string.IsNullOrWhiteSpace(line))
                continue;

            try
            {
                var chunk = JsonSerializer.Deserialize<OllamaStreamChunk>(line);

                if (chunk != null)
                {
                    sb.Append(chunk.response);

                    if (chunk.done)
                        break;
                }
            }
            catch (JsonException)
            {
                // Skip malformed lines
            }
        }

        return sb.ToString();
    }

    private string? ResolveOllamaUrl()
    {
        foreach (var url in Candidates)
        {
            try
            {
                using var test = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
                test.BaseAddress = new Uri(url);
                var response = test.GetAsync("/api/tags").Result;

                if (response.IsSuccessStatusCode)
                    return url;
            }
            catch { }
        }

        return null;
    }
}
