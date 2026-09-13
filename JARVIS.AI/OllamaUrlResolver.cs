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
