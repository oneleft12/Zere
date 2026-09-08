using System.Net.Http.Json;
using JARVIS.AI.Models;

namespace JARVIS.AI;

public class OllamaClient
{
    private readonly HttpClient _httpClient;

    public OllamaClient()
    {
        _httpClient = new HttpClient
        {
            BaseAddress = new Uri("http://localhost:11434")
        };
    }

    public async Task<string> GenerateAsync(string prompt)
    {
        var request = new
        {
            model = "qwen3:8b",
            prompt = $"{SystemPrompt.Jarvis}\n\nПользователь: {prompt}",
            stream = false
        };

        var response = await _httpClient.PostAsJsonAsync("/api/generate", request);

        response.EnsureSuccessStatusCode();

        var result = await response.Content.ReadFromJsonAsync<OllamaResponse>();

        return result?.response ?? "Нет ответа.";
    }
}