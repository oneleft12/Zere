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

    public OllamaClient(string model = "qwen3.5:2b", int timeoutMinutes = 10)
    {
        _model = model;
        _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(timeoutMinutes)
        };

        _resolvedUrl = OllamaUrlResolver.Resolve();

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

            if (string.IsNullOrWhiteSpace(result))
                Console.WriteLine("[Ollama] Пустой ответ от модели.");

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
        using var reader = new StreamReader(stream, Encoding.UTF8, detectEncodingFromByteOrderMarks: true, bufferSize: 8192, leaveOpen: true);

        var buffer = new char[4096];

        while (!reader.EndOfStream)
        {
            var bytesRead = await reader.ReadAsync(buffer, 0, buffer.Length);

            if (bytesRead == 0)
                break;

            var chunk = new string(buffer, 0, bytesRead);

            var lines = chunk.Split('\n', StringSplitOptions.RemoveEmptyEntries);

            foreach (var line in lines)
            {
                var trimmed = line.Trim();

                if (string.IsNullOrEmpty(trimmed))
                    continue;

                try
                {
                    var json = JsonSerializer.Deserialize<OllamaStreamChunk>(trimmed);

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
        }

        return sb.ToString();
    }
}
