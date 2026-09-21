namespace JARVIS.AI;

public static class OllamaUrlResolver
{
    private static readonly string[] Candidates =
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://host.docker.internal:11434"
    ];

    public static string? Resolve()
    {
        // Reuse a single HttpClient across all candidate checks to avoid socket exhaustion.
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };

        foreach (var url in Candidates)
        {
            try
            {
                client.BaseAddress = new Uri(url);
                // .GetAwaiter().GetResult() is used here because Resolve() is called from
                // synchronous contexts (constructor) where no async/await is available.
                var response = client.GetAsync("/api/tags").GetAwaiter().GetResult();

                if (response.IsSuccessStatusCode)
                    return url;
            }
            catch { }
        }

        return null;
    }
}
