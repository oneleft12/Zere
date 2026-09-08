using System.Net.Http.Json;
using System.Net.NetworkInformation;
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

    public OllamaClient(string model = "qwen3.5:2b")
    {
        _model = model;
        _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(5)
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
                stream = false
            };

            var response = await _httpClient.PostAsJsonAsync("/api/generate", request);

            response.EnsureSuccessStatusCode();

            var result = await response.Content.ReadFromJsonAsync<OllamaResponse>();

            return result?.response ?? "Нет ответа от модели.";
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
