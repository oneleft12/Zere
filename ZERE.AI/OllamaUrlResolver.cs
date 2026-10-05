namespace ZERE.AI;

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
                // Construct full URL directly instead of using BaseAddress,
                // because BaseAddress cannot be changed after the first request.
                var requestUrl = url + "/api/tags";
                // .GetAwaiter().GetResult() is used here because Resolve() is called from
                // synchronous contexts (constructor) where no async/await is available.
                var response = client.GetAsync(requestUrl).GetAwaiter().GetResult();

                if (response.IsSuccessStatusCode)
                    return url;
            }
            catch (HttpRequestException)
            {
                // Candidate URL is unreachable or returned an error — try next candidate
            }
            catch (TaskCanceledException)
            {
                // Request timed out — candidate is not available, try next
            }
        }

        return null;
    }
}
