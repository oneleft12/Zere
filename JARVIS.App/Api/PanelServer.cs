using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using JARVIS.AI;
using JARVIS.Core;
using JARVIS.Core.Configuration;
using JARVIS.Core.Logging;
using JARVIS.Core.Plugins;
using JARVIS.Memory.Database;

namespace JARVIS.App.Api;

/// <summary>
/// Локальная панель JARVIS: HTTP API (этап 1 «API-ядро»).
/// Контракт: docs/api/openapi.yaml. Правила безопасности (§6 плана):
/// — слушаем только 127.0.0.1 (loopback-only);
/// — Host должен быть 127.0.0.1/localhost — защита от DNS-rebinding;
/// — Origin, если задан, — только собственный — защита от CSRF;
/// — каждый запрос требует заголовок X-JARVIS-Token (config/panel.token);
/// — ошибки нормализованы: {code, message} — без сырых исключений и путей.
/// </summary>
public sealed class PanelServer : IDisposable
{
    public const int DefaultPort = 8080;

    private const int MaxBodyBytes = 64 * 1024;
    private const int MaxTextLength = 4000;

    // UTF-8 без \uXXXX-эскейпов — как ensure_ascii=False в Python-реализации.
    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };

    private static readonly Dictionary<string, string[]> Routes = new(StringComparer.Ordinal)
    {
        ["/api/health"] = ["GET"],
        ["/api/config"] = ["GET", "POST"],
        ["/api/chat/stream"] = ["GET"],
        ["/api/personality"] = ["GET"],
        ["/api/personality/set"] = ["POST"],
    };

    private static readonly string[] StringFields =
        ["version", "assistantName", "language", "model", "ttsEngine", "voiceReferencePath"];

    private static readonly string[] BoolFields = ["voiceEnabled", "autoMemory"];

    private static readonly string[] AllowedHosts = ["127.0.0.1", "localhost"];

    private readonly HttpListener _listener = new();
    private readonly JarvisConfig _config;
    private readonly JarvisEngine _engine;
    private readonly MemoryRepository _memory;
    private readonly PluginConfig _pluginConfig;
    private readonly string _token;
    private readonly int _port;
    private readonly LogService _log = new();
    private readonly CancellationTokenSource _cts = new();
    private Task? _acceptLoop;
    private volatile bool _started;

    public PanelServer(
        JarvisConfig config,
        JarvisEngine engine,
        MemoryRepository memory,
        PluginConfig pluginConfig,
        string? token = null,
        int port = DefaultPort)
    {
        _config = config;
        _engine = engine;
        _memory = memory;
        _pluginConfig = pluginConfig;
        _token = token ?? PanelToken.LoadOrCreate();
        _port = port;
    }

    public int Port => _port;

    public string Token => _token;

    public void Start()
    {
        // Только loopback: префикс без wildcard, внешний доступ закрыт на уровне http.sys.
        _listener.Prefixes.Add($"http://127.0.0.1:{_port}/");
        _listener.Start();
        _started = true;

        _acceptLoop = Task.Run(AcceptLoopAsync);
    }

    public void Dispose()
    {
        _cts.Cancel();

        if (_started)
        {
            try
            {
                _listener.Stop();
                _listener.Close();
            }
            catch (ObjectDisposedException)
            {
                // уже остановлен
            }

            try
            {
                _acceptLoop?.Wait(TimeSpan.FromSeconds(2));
            }
            catch (AggregateException)
            {
                // цикл приёма завершился вместе с листенером
            }
        }

        _cts.Dispose();
    }

    private async Task AcceptLoopAsync()
    {
        while (!_cts.IsCancellationRequested)
        {
            HttpListenerContext context;

            try
            {
                context = await _listener.GetContextAsync();
            }
            catch (Exception)
            {
                break; // листенер остановлен или закрыт
            }

            _ = Task.Run(() => HandleAsync(context));
        }
    }

    private async Task HandleAsync(HttpListenerContext context)
    {
        var request = context.Request;
        var response = context.Response;

        try
        {
            if (!HostAllowed(request))
            {
                await SendErrorAsync(response, 403, "FORBIDDEN_HOST", "Недопустимый Host.");
                return;
            }

            if (!OriginAllowed(request))
            {
                await SendErrorAsync(response, 403, "FORBIDDEN_ORIGIN", "Недопустимый Origin.");
                return;
            }

            var path = request.Url?.AbsolutePath ?? "/";

            // Статика панели (panel/dist) — без токена: <link>/<img> не умеют
            // шлить заголовки, а токен в HTML читает только same-origin-страница
            // (SOP), Host/Origin проверяются выше для обоих классов запросов.
            if (!path.StartsWith("/api/", StringComparison.Ordinal))
            {
                if (!string.Equals(request.HttpMethod, "GET", StringComparison.Ordinal))
                {
                    await SendErrorAsync(response, 405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.");
                    return;
                }

                await HandleStaticAsync(path, response);
                return;
            }

            if (!TokenAllowed(request))
            {
                await SendErrorAsync(response, 401, "UNAUTHORIZED", "Требуется X-JARVIS-Token.");
                return;
            }

            if (!Routes.TryGetValue(path, out var methods))
            {
                await SendErrorAsync(response, 404, "NOT_FOUND", "Маршрут не найден.");
                return;
            }

            if (!Array.Exists(methods, m => string.Equals(m, request.HttpMethod, StringComparison.Ordinal)))
            {
                await SendErrorAsync(response, 405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.");
                return;
            }

            if (path == "/api/health")
            {
                await HandleHealthAsync(response);
            }
            else if (path == "/api/config")
            {
                if (string.Equals(request.HttpMethod, "GET", StringComparison.Ordinal))
                    await HandleConfigGetAsync(response);
                else
                    await HandleConfigPostAsync(request, response);
            }
            else if (path == "/api/personality")
            {
                await HandlePersonalityGetAsync(response);
            }
            else if (path == "/api/personality/set")
            {
                await HandlePersonalitySetAsync(request, response);
            }
            else
            {
                await HandleChatStreamAsync(request, response);
            }
        }
        catch (Exception ex)
        {
            _log.Error($"PanelServer: {ex.Message}");

            try
            {
                await SendErrorAsync(response, 500, "INTERNAL", "Внутренняя ошибка сервера.");
            }
            catch (Exception)
            {
                // соединение уже закрыто — нормализовать нечего
            }
        }
        finally
        {
            try
            {
                response.OutputStream.Close();
            }
            catch (Exception)
            {
                // поток уже закрыт
            }
        }
    }

    // ── Безопасность ──────────────────────────────────────────────

    private bool HostAllowed(HttpListenerRequest request)
    {
        var host = request.Headers["Host"];

        if (string.IsNullOrEmpty(host))
            host = request.UserHostName; // fallback: host:port от слушателя

        if (string.IsNullOrEmpty(host))
            return true; // клиент не прислал Host

        return AllowedHosts.Contains(HostName(host));
    }

    private bool OriginAllowed(HttpListenerRequest request)
    {
        var origin = request.Headers["Origin"];

        if (string.IsNullOrEmpty(origin))
            return true;

        return origin == $"http://127.0.0.1:{_port}" || origin == $"http://localhost:{_port}";
    }

    private bool TokenAllowed(HttpListenerRequest request)
    {
        var supplied = request.Headers["X-JARVIS-Token"] ?? string.Empty;

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(supplied),
            Encoding.UTF8.GetBytes(_token));
    }

    private static string HostName(string host)
    {
        host = host.Trim();

        if (host.StartsWith('['))
        {
            var end = host.IndexOf(']');
            return end > 0 ? host[1..end] : host;
        }

        var colon = host.IndexOf(':');

        if (colon > 0 && host.Count(c => c == ':') == 1 && int.TryParse(host[(colon + 1)..], out _))
            return host[..colon];

        return host;
    }

    // ── Статика панели (panel/dist) ───────────────────────────────

    private static readonly Dictionary<string, string> StaticContentTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        [".html"] = "text/html; charset=utf-8",
        [".js"] = "text/javascript; charset=utf-8",
        [".css"] = "text/css; charset=utf-8",
        [".json"] = "application/json; charset=utf-8",
        [".map"] = "application/json",
        [".svg"] = "image/svg+xml",
        [".png"] = "image/png",
        [".jpg"] = "image/jpeg",
        [".ico"] = "image/x-icon",
        [".woff2"] = "font/woff2",
        [".txt"] = "text/plain; charset=utf-8",
    };

    private async Task HandleStaticAsync(string path, HttpListenerResponse response)
    {
        var root = Path.Combine(Directory.GetCurrentDirectory(), "panel", "dist");

        if (!Directory.Exists(root))
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", "Панель не собрана: выполните npm run build в panel/.");
            return;
        }

        var target = ResolveStaticTarget(root, path);

        if (target is null)
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", "Ресурс не найден.");
            return;
        }

        if (Path.GetFileName(target) == "index.html")
        {
            // Токен подставляется только в HTML (см. §6 плана: UI читает
            // его при загрузке). Кэшировать нельзя — токен может смениться.
            var html = (await File.ReadAllTextAsync(target)).Replace("__JARVIS_TOKEN__", _token);
            var body = Encoding.UTF8.GetBytes(html);

            response.Headers["Cache-Control"] = "no-cache";
            await WriteBytesAsync(response, 200, "text/html; charset=utf-8", body, cache: false);
            return;
        }

        var bytes = await File.ReadAllBytesAsync(target);
        var contentType = StaticContentTypes.TryGetValue(Path.GetExtension(target), out var known)
            ? known
            : "application/octet-stream";

        await WriteBytesAsync(response, 200, contentType, bytes);
    }

    /// <summary>Безопасное разрешение пути внутри panel/dist (без выхода наружу).</summary>
    private static string? ResolveStaticTarget(string root, string path)
    {
        var relative = Uri.UnescapeDataString(path.TrimStart('/'));

        if (string.IsNullOrEmpty(relative))
            relative = "index.html";

        var parts = relative.Split('/', StringSplitOptions.RemoveEmptyEntries);

        if (parts.Length == 0 || parts.Any(p => p is "." or ".."))
            return null;

        var rootFull = Path.GetFullPath(root);
        var candidate = Path.GetFullPath(Path.Combine(rootFull, Path.Combine(parts)));

        var rootPrefix = rootFull.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;

        if (!candidate.StartsWith(rootPrefix, StringComparison.OrdinalIgnoreCase))
            return null; // выход за пределы каталога статики

        if (Directory.Exists(candidate))
        {
            var index = Path.Combine(candidate, "index.html");
            return File.Exists(index) ? index : null;
        }

        if (File.Exists(candidate))
            return candidate;

        // SPA-фоллбэк: маршруты без расширения отдают index.html (роутер сам)
        if (!Path.GetFileName(candidate).Contains('.'))
        {
            var index = Path.Combine(rootFull, "index.html");
            return File.Exists(index) ? index : null;
        }

        return null;
    }

    // ── Маршруты API ──────────────────────────────────────────────

    private async Task HandleHealthAsync(HttpListenerResponse response)
    {
        string ollama;

        try
        {
            ollama = OllamaUrlResolver.Resolve() is not null ? "ok" : "down";
        }
        catch (Exception)
        {
            ollama = "down"; // пробинг не должен ронять статус
        }

        var modelsDir = Path.Combine("JARVIS.Voice", "Models");

        var whisper = Directory.Exists(modelsDir) && Directory.EnumerateFiles(modelsDir, "*.bin").Any()
            ? "ok"
            : "missing";

        var engineName = _config.TtsEngine is "pocket" or "piper" ? _config.TtsEngine : "piper";

        int count;

        try
        {
            count = _memory.GetAll().Count;
        }
        catch (Exception)
        {
            count = 0;
        }

        var payload = new
        {
            ollama,
            whisper,
            tts = new { engine = engineName, status = "configured" },
            memory = new { count },
            version = _config.Version,
            branch = GitBranch(),
        };

        await SendJsonAsync(response, 200, payload);
    }

    private async Task HandleConfigGetAsync(HttpListenerResponse response)
    {
        await SendJsonAsync(response, 200, _config);
    }

    private async Task HandleConfigPostAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        if (request.ContentLength64 > MaxBodyBytes)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Недопустимый размер тела запроса.");
            return;
        }

        string body;

        using (var reader = new StreamReader(request.InputStream, Encoding.UTF8))
        {
            body = await reader.ReadToEndAsync();
        }

        JsonDocument document;

        try
        {
            document = JsonDocument.Parse(body);
        }
        catch (JsonException)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.");
            return;
        }

        using (document)
        {
            var root = document.RootElement;

            if (root.ValueKind != JsonValueKind.Object)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ожидался JSON-объект конфигурации.");
                return;
            }

            var supplied = new Dictionary<string, JsonElement>(StringComparer.Ordinal);

            foreach (var property in root.EnumerateObject())
                supplied[property.Name] = property.Value.Clone();

            var allowed = new HashSet<string>(StringComparer.Ordinal);
            allowed.UnionWith(StringFields);
            allowed.UnionWith(BoolFields);
            allowed.Add("voiceVolume");
            allowed.Add("ollamaTimeoutMinutes");

            foreach (var name in supplied.Keys)
            {
                if (!allowed.Contains(name))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Неизвестный ключ конфигурации: «{name}».");
                    return;
                }
            }

            foreach (var name in allowed)
            {
                if (!supplied.ContainsKey(name))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Отсутствует обязательный ключ: «{name}».");
                    return;
                }
            }

            var error = ValidateTypes(supplied);

            if (error is not null)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", error);
                return;
            }

            ApplyConfig(supplied);
            _config.Save();

            await SendJsonAsync(response, 200, _config);
        }
    }

    private static string? ValidateTypes(Dictionary<string, JsonElement> supplied)
    {
        foreach (var name in StringFields)
        {
            if (supplied[name].ValueKind != JsonValueKind.String)
                return $"Ключ «{name}» должен быть строкой.";
        }

        foreach (var name in BoolFields)
        {
            if (supplied[name].ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                return $"Ключ «{name}» должен быть логическим значением.";
        }

        var language = supplied["language"].GetString();

        if (language is not ("ru" or "en"))
            return "Ключ «language» допускает только «ru» или «en».";

        var engine = supplied["ttsEngine"].GetString();

        if (engine is not ("pocket" or "piper"))
            return "Ключ «ttsEngine» допускает только «pocket» или «piper».";

        var volume = supplied["voiceVolume"];

        if (volume.ValueKind != JsonValueKind.Number || !volume.TryGetDouble(out var volumeValue))
            return "Ключ «voiceVolume» должен быть числом.";

        if (volumeValue is < 0 or > 1)
            return "Ключ «voiceVolume» должен быть в диапазоне 0…1.";

        var timeout = supplied["ollamaTimeoutMinutes"];

        if (timeout.ValueKind != JsonValueKind.Number || !timeout.TryGetDouble(out var timeoutValue))
            return "Ключ «ollamaTimeoutMinutes» должен быть целым числом.";

        if (timeoutValue != Math.Floor(timeoutValue))
            return "Ключ «ollamaTimeoutMinutes» должен быть целым числом.";

        if (timeoutValue is < 1 or > 120)
            return "Ключ «ollamaTimeoutMinutes» должен быть в диапазоне 1…120.";

        return null;
    }

    private void ApplyConfig(Dictionary<string, JsonElement> supplied)
    {
        _config.Version = supplied["version"].GetString() ?? _config.Version;
        _config.AssistantName = supplied["assistantName"].GetString() ?? _config.AssistantName;
        _config.Language = supplied["language"].GetString() ?? _config.Language;
        _config.Model = supplied["model"].GetString() ?? _config.Model;
        _config.VoiceEnabled = supplied["voiceEnabled"].GetBoolean();
        _config.VoiceVolume = (float)supplied["voiceVolume"].GetDouble();
        _config.AutoMemory = supplied["autoMemory"].GetBoolean();
        _config.OllamaTimeoutMinutes = supplied["ollamaTimeoutMinutes"].GetInt32();
        _config.TtsEngine = supplied["ttsEngine"].GetString() ?? _config.TtsEngine;
        _config.VoiceReferencePath = supplied["voiceReferencePath"].GetString() ?? _config.VoiceReferencePath;
    }

    // ── Личности (смена стиля с персистом — чинит P1-3) ──────────

    private object? BuildPersonalityPayload()
    {
        var active = _engine.PluginManager.ActivePersonality;

        if (active is null)
            return null;

        return new
        {
            activeId = active.Id,
            activeStyle = active.Style.ToString(),
            styles = active.GetAvailableStyles(),
        };
    }

    private async Task HandlePersonalityGetAsync(HttpListenerResponse response)
    {
        var payload = BuildPersonalityPayload();

        if (payload is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Сервис личностей не готов.");
            return;
        }

        await SendJsonAsync(response, 200, payload);
    }

    private async Task HandlePersonalitySetAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        if (BuildPersonalityPayload() is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Сервис личностей не готов.");
            return;
        }

        // Без хранилища стиль не сохранится — не применяем, чтобы не
        // обещать пользователю персист, которого не будет.
        if (_pluginConfig is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Хранилище настроек не готово.");
            return;
        }

        if (request.ContentLength64 > MaxBodyBytes)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Недопустимый размер тела запроса.");
            return;
        }

        string body;

        using (var reader = new StreamReader(request.InputStream, Encoding.UTF8))
        {
            body = await reader.ReadToEndAsync();
        }

        JsonDocument document;

        try
        {
            document = JsonDocument.Parse(body);
        }
        catch (JsonException)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.");
            return;
        }

        using (document)
        {
            var root = document.RootElement;

            if (root.ValueKind != JsonValueKind.Object)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ожидался JSON-объект {styleId}.");
                return;
            }

            foreach (var property in root.EnumerateObject())
            {
                if (!string.Equals(property.Name, "styleId", StringComparison.Ordinal))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Неизвестный ключ: «{property.Name}».");
                    return;
                }
            }

            if (!root.TryGetProperty("styleId", out var styleElement))
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Отсутствует обязательный ключ: «styleId».");
                return;
            }

            if (styleElement.ValueKind != JsonValueKind.String)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ключ «styleId» должен быть строкой.");
                return;
            }

            var styleId = styleElement.GetString() ?? string.Empty;
            var active = _engine.PluginManager.ActivePersonality!;
            var canonical = active.GetAvailableStyles()
                .FirstOrDefault(s => string.Equals(s, styleId, StringComparison.OrdinalIgnoreCase));

            if (canonical is null)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Неизвестный стиль: «{styleId}».");
                return;
            }

            active.SetStyle(canonical);

            _pluginConfig.ActivePersonalityId = active.Id;
            _pluginConfig.ActivePersonalityStyle = canonical;
            PluginConfig.Save(_pluginConfig);

            await SendJsonAsync(response, 200, BuildPersonalityPayload());
        }
    }

    private async Task HandleChatStreamAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        var text = request.QueryString["text"] ?? string.Empty;

        if (string.IsNullOrWhiteSpace(text))
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Параметр text обязателен.");
            return;
        }

        if (text.Length > MaxTextLength)
        {
            await SendErrorAsync(
                response, 400, "VALIDATION_ERROR",
                $"Текст слишком длинный (максимум {MaxTextLength} символов).");
            return;
        }

        response.StatusCode = 200;
        response.ContentType = "text/event-stream; charset=utf-8";
        response.Headers["Cache-Control"] = "no-cache";
        response.SendChunked = true;
        response.KeepAlive = false;

        string answer;

        try
        {
            answer = await _engine.ProcessAsync(text);
        }
        catch (Exception ex)
        {
            // сырую ошибку клиенту не показываем
            _log.Error($"PanelServer.chat: {ex.Message}");
            await WriteEventAsync(response, "error",
                new { code = "INTERNAL", message = "Не удалось обработать запрос." });
            return;
        }

        // Этап 1: полный ответ одним событием token; потоковая токенизация
        // появится, когда OllamaClient откроет посимвольный стриминг.
        await WriteEventAsync(response, "token", new { text = answer });
        await WriteEventAsync(response, "done", new { answer });
    }

    // ── Помощники ответа ──────────────────────────────────────────

    private static async Task SendErrorAsync(HttpListenerResponse response, int status, string code, string message)
    {
        await SendJsonAsync(response, status, new { code, message });
    }

    private static async Task SendJsonAsync(HttpListenerResponse response, int status, object payload)
    {
        var body = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload, WriteOptions));
        await WriteBytesAsync(response, status, "application/json; charset=utf-8", body, cache: false);
    }

    private static async Task WriteBytesAsync(
        HttpListenerResponse response, int status, string contentType, byte[] body, bool cache = true)
    {
        response.StatusCode = status;
        response.ContentType = contentType;

        if (!cache)
            response.Headers["Cache-Control"] = "no-store";

        response.ContentLength64 = body.Length;

        await response.OutputStream.WriteAsync(body);
        await response.OutputStream.FlushAsync();
    }

    private static async Task WriteEventAsync(HttpListenerResponse response, string eventName, object data)
    {
        var json = JsonSerializer.Serialize(data, WriteOptions);
        var chunk = Encoding.UTF8.GetBytes($"event: {eventName}\ndata: {json}\n\n");

        await response.OutputStream.WriteAsync(chunk);
        await response.OutputStream.FlushAsync();
    }

    // ── Прочее ────────────────────────────────────────────────────

    private static string GitBranch()
    {
        try
        {
            var text = File.ReadAllText(Path.Combine(".git", "HEAD")).Trim();
            const string prefix = "ref: refs/heads/";

            if (text.StartsWith(prefix, StringComparison.Ordinal))
                return text[prefix.Length..];

            return string.IsNullOrEmpty(text) ? "unknown" : "detached";
        }
        catch (Exception)
        {
            return "unknown";
        }
    }
}
