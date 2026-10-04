using System.Net;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Text.Json.Serialization;
using JARVIS.AI;
using JARVIS.Core;
using JARVIS.Core.Configuration;
using JARVIS.Core.Logging;
using JARVIS.Core.Plugins;
using JARVIS.Memory.Database;
using JARVIS.Memory.Models;
using JARVIS.Tools.Applications;
using JARVIS.Tools.Applications.Indexing;
using JARVIS.Tools.Windows;
using JARVIS.Tools.Windows.Processes;
using JARVIS.Voice;

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
    private const int MaxVoiceTestLength = 500;

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
        ["/api/history"] = ["GET", "DELETE"],
        ["/api/memory"] = ["GET", "POST"],
        ["/api/processes"] = ["GET"],
        ["/api/apps"] = ["GET"],
        ["/api/apps/reindex"] = ["POST"],
        ["/api/logs"] = ["GET"],
        ["/api/plugins"] = ["GET"],
        ["/api/voice"] = ["GET", "POST"],
        ["/api/voice/reference"] = ["POST"],
        ["/api/voice/test"] = ["POST"],
        ["/api/voice/listen"] = ["POST"],
    };

    private const string MemoryPrefix = "/api/memory/";

    // Динамические маршруты подтверждаемых действий (этап 4 плана, §6):
    //   POST /api/processes/{pid}/kill — двухшаговый подтверждённый запрос;
    //   POST /api/power/{action}       — питание через SafeActionManager.
    private const string KillPrefix = "/api/processes/";
    private const string KillSuffix = "/kill";
    private const string PowerPrefix = "/api/power/";
    private const int TtlSeconds = 60; // тот же срок, что у SafeActionManager
    private const int MaxProcessQueryLength = 100;
    private const int MaxAppQueryLength = 200;
    private const int LogDefaultLimit = 50;
    private const int LogMaxLimit = 500;
    private const int MaxPid = int.MaxValue;
    private static readonly string[] PowerActions = ["shutdown", "restart", "sleep"];
    private const int HistoryDefaultLimit = 50;
    private const int HistoryMaxLimit = 500;
    private const int MaxHistorySearchLength = 200;
    private const int MaxMemoryKeyLength = 200;
    private const int MaxMemoryValueLength = 2000;
    private const int MaxMemoryCategoryLength = 100;

    private static readonly string[] StringFields =
        ["version", "assistantName", "language", "model", "ttsEngine", "voiceReferencePath"];

    private static readonly string[] BoolFields = ["voiceEnabled", "autoMemory"];

    private static readonly string[] AllowedHosts = ["127.0.0.1", "localhost"];

    private readonly HttpListener _listener = new();
    private readonly JarvisConfig _config;
    private readonly JarvisEngine _engine;
    private readonly MemoryRepository _memory;
    private readonly ConversationRepository _conversations;
    private readonly PluginConfig _pluginConfig;
    private readonly ProcessService? _processes;
    private readonly SafeActionManager? _safeActions;
    private readonly ApplicationLauncher? _apps;
    private readonly VoiceManager? _voice;
    private readonly object _challengeLock = new();

    // Одноразовый токен подтверждения (kill/power): (token, action, issuedAt).
    private (string Token, string Action, long IssuedAt)? _challenge;

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
        ConversationRepository conversations,
        PluginConfig pluginConfig,
        ProcessService? processes = null,
        SafeActionManager? safeActions = null,
        ApplicationLauncher? apps = null,
        VoiceManager? voice = null,
        string? token = null,
        int port = DefaultPort)
    {
        _config = config;
        _engine = engine;
        _memory = memory;
        _conversations = conversations;
        _pluginConfig = pluginConfig;
        _processes = processes;
        _safeActions = safeActions;
        _apps = apps;
        _voice = voice;
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

            // Динамический маршрут DELETE /api/memory/{id}
            if (path.StartsWith(MemoryPrefix, StringComparison.Ordinal))
            {
                if (!string.Equals(request.HttpMethod, "DELETE", StringComparison.Ordinal))
                {
                    await SendErrorAsync(response, 405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.");
                    return;
                }

                await HandleMemoryDeleteAsync(path[MemoryPrefix.Length..], response);
                return;
            }

            // Динамический маршрут POST /api/processes/{pid}/kill
            if (path.StartsWith(KillPrefix, StringComparison.Ordinal))
            {
                if (!string.Equals(request.HttpMethod, "POST", StringComparison.Ordinal))
                {
                    await SendErrorAsync(response, 405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.");
                    return;
                }

                await HandleProcessKillAsync(path[KillPrefix.Length..], request, response);
                return;
            }

            // Динамический маршрут POST /api/power/{action}
            if (path.StartsWith(PowerPrefix, StringComparison.Ordinal))
            {
                if (!string.Equals(request.HttpMethod, "POST", StringComparison.Ordinal))
                {
                    await SendErrorAsync(response, 405, "METHOD_NOT_ALLOWED", "Метод не поддерживается.");
                    return;
                }

                await HandlePowerAsync(path[PowerPrefix.Length..], request, response);
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
            else if (path == "/api/history")
            {
                if (string.Equals(request.HttpMethod, "GET", StringComparison.Ordinal))
                    await HandleHistoryGetAsync(request, response);
                else
                    await HandleHistoryDeleteAsync(request, response);
            }
            else if (path == "/api/memory")
            {
                if (string.Equals(request.HttpMethod, "GET", StringComparison.Ordinal))
                    await HandleMemoryGetAsync(request, response);
                else
                    await HandleMemoryPostAsync(request, response);
            }
            else if (path == "/api/processes")
            {
                await HandleProcessesGetAsync(request, response);
            }
            else if (path == "/api/apps")
            {
                await HandleAppsGetAsync(request, response);
            }
            else if (path == "/api/apps/reindex")
            {
                await HandleAppsReindexAsync(response);
            }
            else if (path == "/api/logs")
            {
                await HandleLogsGetAsync(request, response);
            }
            else if (path == "/api/plugins")
            {
                await HandlePluginsGetAsync(response);
            }
            else if (path == "/api/voice")
            {
                if (string.Equals(request.HttpMethod, "GET", StringComparison.Ordinal))
                    await HandleVoiceGetAsync(response);
                else
                    await HandleVoicePostAsync(request, response);
            }
            else if (path == "/api/voice/reference")
            {
                await HandleVoiceReferenceAsync(response);
            }
            else if (path == "/api/voice/test")
            {
                await HandleVoiceTestAsync(request, response);
            }
            else if (path == "/api/voice/listen")
            {
                await HandleVoiceListenAsync(response);
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
            allowed.Add("llmKeepAlive");
            allowed.Add("llmMaxTokens");
            allowed.Add("llmTimeoutSeconds");

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

        var error = ValidateInt(supplied, "llmKeepAlive", -1, 86400);
        if (error is not null)
            return error;

        error = ValidateInt(supplied, "llmMaxTokens", 16, 4096);
        if (error is not null)
            return error;

        error = ValidateInt(supplied, "llmTimeoutSeconds", 5, 600);
        if (error is not null)
            return error;

        return null;
    }

    /// <summary>Целое число в диапазоне [min, max] (ключи LLM, анализ S5).</summary>
    private static string? ValidateInt(
        Dictionary<string, JsonElement> supplied, string key, int min, int max)
    {
        var element = supplied[key];

        if (element.ValueKind != JsonValueKind.Number || !element.TryGetDouble(out var value))
            return $"Ключ «{key}» должен быть целым числом.";

        if (value != Math.Floor(value))
            return $"Ключ «{key}» должен быть целым числом.";

        if (value < min || value > max)
            return $"Ключ «{key}» должен быть в диапазоне {min}…{max}.";

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
        _config.LlmKeepAlive = supplied["llmKeepAlive"].GetInt32();
        _config.LlmMaxTokens = supplied["llmMaxTokens"].GetInt32();
        _config.LlmTimeoutSeconds = supplied["llmTimeoutSeconds"].GetInt32();
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

    // ── История (/api/history) ────────────────────────────────────

    private async Task HandleHistoryGetAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        if (!TryReadIntQuery(request, "limit", HistoryDefaultLimit, 1, HistoryMaxLimit, out var limit, out var limitError))
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", limitError!);
            return;
        }

        if (!TryReadIntQuery(request, "offset", 0, 0, 1_000_000_000, out var offset, out var offsetError))
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", offsetError!);
            return;
        }

        var search = request.QueryString["search"] ?? "";

        if (search.Length > MaxHistorySearchLength)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Параметр «search» длиннее {MaxHistorySearchLength} символов.");
            return;
        }

        var items = _conversations.GetPage(limit, offset, search)
            .Select(c => new
            {
                Id = c.Id,
                UserMessage = c.UserMessage,
                JarvisResponse = c.JarvisResponse,
                Timestamp = c.Timestamp.ToString("O"),
            })
            .ToList();

        await SendJsonAsync(response, 200, new { Items = items, Total = _conversations.Count(search) });
    }

    private async Task HandleHistoryDeleteAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        var document = await ReadJsonObjectAsync(request, response);

        if (document is null)
            return;

        using (document)
        {
            var root = document.RootElement;

            if (root.ValueKind != JsonValueKind.Object)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ожидался JSON-объект {confirm: \"DELETE\"}.");
                return;
            }

            foreach (var property in root.EnumerateObject())
            {
                if (!string.Equals(property.Name, "confirm", StringComparison.Ordinal))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Неизвестный ключ: «{property.Name}».");
                    return;
                }
            }

            if (!root.TryGetProperty("confirm", out var confirm))
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Отсутствует обязательный ключ: «confirm».");
                return;
            }

            if (confirm.ValueKind != JsonValueKind.String || !string.Equals(confirm.GetString(), "DELETE", StringComparison.Ordinal))
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ожидалось подтверждение confirm = \"DELETE\".");
                return;
            }

            var deleted = _conversations.Count();
            _conversations.ClearHistory();

            await SendJsonAsync(response, 200, new { Deleted = deleted });
        }
    }

    // ── Память (/api/memory, /api/memory/{id}) ────────────────────

    private async Task HandleMemoryGetAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        var search = request.QueryString["search"] ?? "";

        var items = (string.IsNullOrEmpty(search) ? _memory.GetAll() : _memory.Search(search))
            .Select(ToMemoryPayload)
            .ToList();

        await SendJsonAsync(response, 200, new { Items = items });
    }

    private async Task HandleMemoryPostAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        var document = await ReadJsonObjectAsync(request, response);

        if (document is null)
            return;

        using (document)
        {
            var root = document.RootElement;

            if (root.ValueKind != JsonValueKind.Object)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ожидался JSON-объект записи памяти.");
                return;
            }

            foreach (var property in root.EnumerateObject())
            {
                if (property.Name is not ("key" or "value" or "category"))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Неизвестный ключ: «{property.Name}».");
                    return;
                }
            }

            foreach (var required in new[] { "key", "value" })
            {
                if (!root.TryGetProperty(required, out var element))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Отсутствует обязательный ключ: «{required}».");
                    return;
                }

                if (element.ValueKind != JsonValueKind.String)
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Ключ «{required}» должен быть строкой.");
                    return;
                }
            }

            var key = root.GetProperty("key").GetString()!;
            var value = root.GetProperty("value").GetString()!;

            if (string.IsNullOrWhiteSpace(key))
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ключ «key» не может быть пустым.");
                return;
            }

            if (key.Length > MaxMemoryKeyLength)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Ключ «key» длиннее {MaxMemoryKeyLength} символов.");
                return;
            }

            if (value.Length > MaxMemoryValueLength)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Значение длиннее {MaxMemoryValueLength} символов.");
                return;
            }

            var category = "User";

            if (root.TryGetProperty("category", out var categoryElement))
            {
                if (categoryElement.ValueKind != JsonValueKind.String)
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ключ «category» должен быть строкой.");
                    return;
                }

                category = categoryElement.GetString()!;

                if (string.IsNullOrWhiteSpace(category))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ключ «category» не может быть пустым.");
                    return;
                }

                if (category.Length > MaxMemoryCategoryLength)
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Ключ «category» длиннее {MaxMemoryCategoryLength} символов.");
                    return;
                }
            }

            _memory.Remember(key, value, category);

            var saved = _memory.Find(key);

            if (saved is null)
            {
                await SendErrorAsync(response, 503, "NOT_READY", "Хранилище памяти не готово.");
                return;
            }

            await SendJsonAsync(response, 200, ToMemoryPayload(saved));
        }
    }

    private async Task HandleMemoryDeleteAsync(string rawId, HttpListenerResponse response)
    {
        if (rawId.Length == 0 || !rawId.All(char.IsAsciiDigit))
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Идентификатор памяти должен быть числом.");
            return;
        }

        if (!long.TryParse(rawId, out var id) || !_memory.ForgetById(id))
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", "Запись памяти не найдена.");
            return;
        }

        await SendJsonAsync(response, 200, new { Deleted = true });
    }

    // ── Приложения (этап 4, §6 плана) ─────────────────────────────

    /// <summary>Индексированные приложения; {q} — подстрочный поиск по имени/алиасам.</summary>
    private async Task HandleAppsGetAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        var query = request.QueryString["q"] ?? string.Empty;

        if (query.Length > MaxAppQueryLength)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Параметр «q» длиннее {MaxAppQueryLength} символов.");
            return;
        }

        if (_apps is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Сервис приложений не готов.");
            return;
        }

        var items = _apps.GetInstalledApplications().Values
            .Where(app => MatchesAppQuery(app, query))
            .OrderByDescending(app => app.Priority)
            .ThenBy(app => app.Name, StringComparer.Ordinal)
            .Select(AppPayload)
            .ToList();

        await SendJsonAsync(response, 200, new { items, total = items.Count });
    }

    /// <summary>Полная переиндексация: сканеры реестра/меню/AppPaths/LocalAppData.</summary>
    private async Task HandleAppsReindexAsync(HttpListenerResponse response)
    {
        if (_apps is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Сервис приложений не готов.");
            return;
        }

        var started = Stopwatch.StartNew();
        _apps.RebuildIndex();
        started.Stop();

        await SendJsonAsync(response, 200, new
        {
            Count = _apps.GetInstalledApplications().Count,
            DurationMs = (int)started.ElapsedMilliseconds,
        });
    }

    /// <summary>Подстроковый поиск по имени и алиасам без учёта регистра.</summary>
    private static bool MatchesAppQuery(AppInfo app, string query)
    {
        if (query.Length == 0)
            return true;

        if (app.Name.Contains(query, StringComparison.OrdinalIgnoreCase))
            return true;

        return app.Aliases.Any(alias => alias.Contains(query, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>Строка списка приложений под контракт (camelCase, lastSeen «O»).</summary>
    private static object AppPayload(AppInfo app) => new
    {
        Name = app.Name,
        ExecutablePath = app.ExecutablePath,
        Source = app.Source,
        Category = app.Category,
        Priority = app.Priority,
        Aliases = app.Aliases,
        LastSeen = app.LastSeen.ToString("O"),
    };

    // ── Журнал (этап 4, §6 плана) ─────────────────────────────────

    // Журнал: строка сессии `[ts] [LEVEL] msg` vs errors.log `[ts] [LEVEL] [src] msg`.
    // Источник определяется по ИМЕНИ файла, а не по разбору строки: сообщение
    // ошибки может само начинаться с квадратных скобок (например, [Errno 32]).
    private static readonly Regex LogSessionLine = new(
        @"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([A-Za-z]+)\] (.*)$");

    private static readonly Regex LogErrorsLine = new(
        @"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[([A-Za-z]+)\] \[([^\]]+)\] (.*)$");

    /// <summary>Сессионные журналы + errors.log: фильтр по level, пагинация как в истории.</summary>
    private async Task HandleLogsGetAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        if (!TryReadIntQuery(request, "limit", LogDefaultLimit, 1, LogMaxLimit, out var limit, out var limitError))
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", limitError!);
            return;
        }

        if (!TryReadIntQuery(request, "offset", 0, 0, 1_000_000_000, out var offset, out var offsetError))
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", offsetError!);
            return;
        }

        var level = request.QueryString["level"] ?? "";

        if (level.Length > 0 && level is not ("info" or "warn" or "error"))
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Параметр level должен быть одним из: info, warn, error.");
            return;
        }

        var entries = ReadLogEntries(Path.Combine(Directory.GetCurrentDirectory(), "logs"), level);

        await SendJsonAsync(response, 200, new
        {
            items = entries.Skip(offset).Take(limit).ToList(),
            total = entries.Count,
        });
    }

    /// <summary>
    /// Файлы журнала по имени DESC, затем стабильная сортировка по времени DESC
    /// (как в Python-реализации). Неразобранные строки пропускаются.
    /// </summary>
    private static List<object> ReadLogEntries(string folder, string level)
    {
        var entries = new List<(string Time, string Level, string Message, string? Source)>();

        if (!Directory.Exists(folder))
            return entries.Cast<object>().ToList();

        var files = Directory.EnumerateFiles(folder, "*.log")
            .Select(path => Path.GetFileName(path) ?? "")
            .Where(name => name.Length > 0)
            .OrderByDescending(name => name, StringComparer.Ordinal);

        foreach (var name in files)
        {
            var isErrors = string.Equals(name, "errors.log", StringComparison.Ordinal);
            var pattern = isErrors ? LogErrorsLine : LogSessionLine;

            string[] lines;

            try
            {
                lines = File.ReadAllLines(Path.Combine(folder, name));
            }
            catch (IOException)
            {
                continue;
            }
            catch (UnauthorizedAccessException)
            {
                continue;
            }

            foreach (var line in lines)
            {
                var match = pattern.Match(line);

                if (!match.Success)
                    continue;

                var itemLevel = match.Groups[2].Value.ToLowerInvariant();

                if (level.Length > 0 && !string.Equals(itemLevel, level, StringComparison.Ordinal))
                    continue;

                var message = isErrors ? match.Groups[4].Value : match.Groups[3].Value;
                string? source = isErrors ? match.Groups[3].Value : null;

                entries.Add((match.Groups[1].Value.Replace(' ', 'T'), itemLevel, message, source));
            }
        }

        return entries
            .OrderByDescending(entry => entry.Time, StringComparer.Ordinal)
            .Select(entry => (object)new
            {
                Time = entry.Time,
                Level = entry.Level,
                Message = entry.Message,
                Source = entry.Source,
            })
            .ToList();
    }

    // ── Плагины (этап 4, §6 плана) ────────────────────────────────

    /// <summary>Инвентарь плагинов и активная личность (без флага enabled: его нет).</summary>
    private async Task HandlePluginsGetAsync(HttpListenerResponse response)
    {
        var manager = _engine.PluginManager;

        var items = manager.Plugins
            .Select(plugin => new
            {
                Id = plugin.Id,
                Name = plugin.Name,
                Description = plugin.Description,
                Version = plugin.Version,
                Author = plugin.Author,
                Type = plugin.Type.ToString(),
            })
            .ToList();

        var active = manager.ActivePersonality;

        await SendJsonAsync(response, 200, new
        {
            items,
            // Честное false: пайплайн — 9 фиксированных обработчиков,
            // плагины-обработчики в него не встраиваются.
            handlersConnected = false,
            commandHandlersCount = manager.CommandHandlers.Count,
            activePersonality = active is null
                ? null
                : (object?)new { Id = active.Id, Style = active.Style.ToString() },
        });
    }

    // ── Голос (этап 4, §6 плана) ──────────────────────────────────

    /// <summary>Что эта реализация умеет фактически (описания — в openapi).</summary>
    private static object BuildVoiceCapabilities(bool voiceAvailable) => new
    {
        recordReference = true,   // запись референса — только в C#-версии
        pocketCloning = true,     // PocketTTS только в C#-версии
        speechSpeedConfig = true, // piper получает --length_scale при Initialize
        liveVolumeApply = true,   // Volume читается на каждое воспроизведение
        sttTest = voiceAvailable,
    };

    private async Task HandleVoiceGetAsync(HttpListenerResponse response)
    {
        if (_voice is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Голосовой модуль не готов.");
            return;
        }

        await SendJsonAsync(response, 200, new
        {
            voiceEnabled = _config.VoiceEnabled,
            voiceVolume = _config.VoiceVolume,
            ttsEngine = _config.TtsEngine,
            voiceReferencePath = _config.VoiceReferencePath,
            capabilities = BuildVoiceCapabilities(_voice.IsVoiceAvailable),
        });
    }

    /// <summary>Обновление голоса: громкость применяется сразу, остальное — после рестарта.</summary>
    private async Task HandleVoicePostAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        if (_voice is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Голосовой модуль не готов.");
            return;
        }

        var document = await ReadRequestBodyObjectAsync(request, response);

        if (document is null)
            return;

        using (document)
        {
            var supplied = new Dictionary<string, JsonElement>(StringComparer.Ordinal);

            foreach (var property in document.RootElement.EnumerateObject())
                supplied[property.Name] = property.Value.Clone();

            var error = ValidateVoicePayload(supplied);

            if (error is not null)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", error);
                return;
            }

            var beforeEnabled = _config.VoiceEnabled;
            var beforeEngine = _config.TtsEngine;
            var beforeReference = _config.VoiceReferencePath;

            if (supplied.TryGetValue("voiceVolume", out var volumeElement))
            {
                var volume = (float)volumeElement.GetDouble();
                _config.VoiceVolume = volume;
                // liveVolumeApply: VoiceConfig читается на каждое воспроизведение
                _voice.Config.Volume = volume;
            }

            if (supplied.TryGetValue("voiceEnabled", out var enabledElement))
                _config.VoiceEnabled = enabledElement.GetBoolean();

            if (supplied.TryGetValue("ttsEngine", out var engineElement))
                _config.TtsEngine = engineElement.GetString() ?? _config.TtsEngine;

            if (supplied.TryGetValue("voiceReferencePath", out var referenceElement))
                _config.VoiceReferencePath = referenceElement.GetString() ?? _config.VoiceReferencePath;

            _config.Save();

            var appliedOnRestart =
                _config.VoiceEnabled != beforeEnabled ||
                !string.Equals(_config.TtsEngine, beforeEngine, StringComparison.Ordinal) ||
                !string.Equals(_config.VoiceReferencePath, beforeReference, StringComparison.Ordinal);

            await SendJsonAsync(response, 200, new
            {
                voiceEnabled = _config.VoiceEnabled,
                voiceVolume = _config.VoiceVolume,
                ttsEngine = _config.TtsEngine,
                voiceReferencePath = _config.VoiceReferencePath,
                appliedOnRestart,
            });
        }
    }

    /// <summary>Запись WAV-референса голоса с сохранением пути в конфигурации.</summary>
    private async Task HandleVoiceReferenceAsync(HttpListenerResponse response)
    {
        if (_voice is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Голосовой модуль не готов.");
            return;
        }

        var path = await _voice.RecordVoiceReferenceAsync();

        if (string.IsNullOrEmpty(path))
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Не удалось записать референс голоса.");
            return;
        }

        _config.VoiceReferencePath = path;
        _config.Save();

        await SendJsonAsync(response, 200, new { voiceReferencePath = path });
    }

    /// <summary>Синтез фразы: 503, если TTS не инициализирован (как в консоли).</summary>
    private async Task HandleVoiceTestAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        if (_voice is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Голосовой модуль не готов.");
            return;
        }

        var document = await ReadRequestBodyObjectAsync(request, response);

        if (document is null)
            return;

        using (document)
        {
            var root = document.RootElement;

            foreach (var property in root.EnumerateObject())
            {
                if (!string.Equals(property.Name, "text", StringComparison.Ordinal))
                {
                    await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Неизвестный ключ: «{property.Name}».");
                    return;
                }
            }

            if (!root.TryGetProperty("text", out var textElement) ||
                textElement.ValueKind != JsonValueKind.String)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ключ «text» должен быть строкой.");
                return;
            }

            var text = textElement.GetString() ?? "";

            if (string.IsNullOrWhiteSpace(text))
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ключ «text» не может быть пустым.");
                return;
            }

            if (text.Length > MaxVoiceTestLength)
            {
                await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Ключ «text» длиннее {MaxVoiceTestLength} символов.");
                return;
            }

            if (!_voice.IsTtsAvailable)
            {
                await SendErrorAsync(response, 503, "NOT_READY", "Синтез речи недоступен.");
                return;
            }

            await _voice.SpeakAsync(text);

            await SendJsonAsync(response, 200, new { status = "ok" });
        }
    }

    /// <summary>Тест STT: распознавание одной фразы с микрофона.</summary>
    private async Task HandleVoiceListenAsync(HttpListenerResponse response)
    {
        if (_voice is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Голосовой модуль не готов.");
            return;
        }

        if (!_voice.IsVoiceAvailable)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Распознавание речи недоступно.");
            return;
        }

        var text = await _voice.ListenAsync();

        await SendJsonAsync(response, 200, new { text });
    }

    private static string? ValidateVoicePayload(Dictionary<string, JsonElement> supplied)
    {
        string[] allowed = ["voiceEnabled", "voiceVolume", "ttsEngine", "voiceReferencePath"];

        foreach (var name in supplied.Keys)
        {
            if (Array.IndexOf(allowed, name) < 0)
                return $"Неизвестный ключ голосовых настроек: «{name}».";
        }

        if (supplied.Count == 0)
            return "Не задано ни одного голосового поля.";

        if (supplied.TryGetValue("voiceEnabled", out var enabled) &&
            enabled.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
            return "Ключ «voiceEnabled» должен быть логическим значением.";

        if (supplied.TryGetValue("voiceVolume", out var volume))
        {
            if (volume.ValueKind != JsonValueKind.Number || !volume.TryGetDouble(out var value))
                return "Ключ «voiceVolume» должен быть числом.";

            if (value is < 0 or > 1)
                return "Ключ «voiceVolume» должен быть в диапазоне 0…1.";
        }

        if (supplied.TryGetValue("ttsEngine", out var engine) &&
            (engine.ValueKind != JsonValueKind.String || engine.GetString() is not ("pocket" or "piper")))
            return "Ключ «ttsEngine» допускает только «pocket» или «piper».";

        if (supplied.TryGetValue("voiceReferencePath", out var referencePath) &&
            referencePath.ValueKind != JsonValueKind.String)
            return "Ключ «voiceReferencePath» должен быть строкой.";

        return null;
    }

    // ── Процессы и питание (этап 4, §6 плана) ────────────────────

    /// <summary>Список процессов: {q} — подстрочный поиск по имени.</summary>
    private async Task HandleProcessesGetAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        var query = request.QueryString["q"] ?? string.Empty;

        if (query.Length > MaxProcessQueryLength)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", $"Параметр «q» длиннее {MaxProcessQueryLength} символов.");
            return;
        }

        if (_processes is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Сервис процессов не готов.");
            return;
        }

        var items = (query.Length > 0 ? _processes.Search(query) : _processes.GetProcesses())
            .Select(ProcessPayload)
            .ToList();

        await SendJsonAsync(response, 200, new { items });
    }

    /// <summary>Завершение процесса в два шага: токен, затем {confirm, ttlToken}.</summary>
    private async Task HandleProcessKillAsync(string rawPath, HttpListenerRequest request, HttpListenerResponse response)
    {
        if (!rawPath.EndsWith(KillSuffix, StringComparison.Ordinal))
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", "Маршрут не найден.");
            return;
        }

        var pidText = rawPath[..^KillSuffix.Length];

        if (pidText.Length == 0
            || !pidText.All(char.IsAsciiDigit)
            || !int.TryParse(pidText, NumberStyles.None, CultureInfo.InvariantCulture, out var pid)
            || pid < 1
            || pid > MaxPid)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "PID должен быть положительным целым числом.");
            return;
        }

        var payload = await ReadRequestBodyObjectAsync(request, response);
        if (payload is null)
            return;

        if (_processes is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Сервис процессов не готов.");
            return;
        }

        var info = FindProcess(pid);

        if (info is null)
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", $"Процесс с PID {pid} не найден.");
            return;
        }

        if (ProcessService.IsProtected(info.Name))
        {
            await SendErrorAsync(response, 400, "PROTECTED", $"Процесс «{info.Name}» защищён от завершения.");
            return;
        }

        var action = $"kill:{pid}";

        // Шаг 1: пустое тело — выдаём одноразовый токен с серверным сроком.
        if (IsEmptyObject(payload))
        {
            await SendJsonAsync(response, 200, new
            {
                Status = "pending",
                Pid = pid,
                Name = info.Name,
                TtlToken = IssueChallenge(action),
                ExpiresInSeconds = TtlSeconds,
            });
            return;
        }

        // Шаг 2: подтверждение.
        var error = ValidateTtlPayload(payload.RootElement, "KILL");
        if (error is not null)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", error);
            return;
        }

        var problem = ConsumeChallenge(payload.RootElement.GetProperty("ttlToken").GetString(), action);
        if (problem is not null)
        {
            await SendErrorAsync(response, 400, problem.Value.Code, problem.Value.Message);
            return;
        }

        // Повторная проверка: PID могли переиспользовать за время диалога.
        info = FindProcess(pid);

        if (info is null)
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", $"Процесс с PID {pid} не найден.");
            return;
        }

        if (ProcessService.IsProtected(info.Name))
        {
            await SendErrorAsync(response, 400, "PROTECTED", $"Процесс «{info.Name}» защищён от завершения.");
            return;
        }

        if (!_processes.KillPid(pid))
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", "Процесс не найден или уже завершён.");
            return;
        }

        await SendJsonAsync(response, 200, new { Status = "killed", Pid = pid, Name = info.Name });
    }

    /// <summary>Питание через штатный SafeActionManager + серверный TTL.</summary>
    private async Task HandlePowerAsync(string action, HttpListenerRequest request, HttpListenerResponse response)
    {
        if (!PowerActions.Contains(action))
        {
            await SendErrorAsync(response, 404, "NOT_FOUND", "Неизвестное действие питания.");
            return;
        }

        if (_safeActions is null)
        {
            await SendErrorAsync(response, 503, "NOT_READY", "Сервис питания не готов.");
            return;
        }

        var payload = await ReadRequestBodyObjectAsync(request, response);
        if (payload is null)
            return;

        var pending = action switch
        {
            "shutdown" => PendingAction.Shutdown,
            "restart" => PendingAction.Restart,
            _ => PendingAction.Sleep,
        };

        // Шаг 1: команда поставлена в очередь подтверждения, токен выдан.
        if (IsEmptyObject(payload))
        {
            _safeActions.Request(pending);

            await SendJsonAsync(response, 200, new
            {
                Status = "pending",
                Action = action,
                TtlToken = IssueChallenge($"power:{action}"),
                ExpiresInSeconds = TtlSeconds,
            });
            return;
        }

        var error = ValidateTtlPayload(payload.RootElement, "POWER");
        if (error is not null)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", error);
            return;
        }

        var problem = ConsumeChallenge(payload.RootElement.GetProperty("ttlToken").GetString(), $"power:{action}");
        if (problem is not null)
        {
            await SendErrorAsync(response, 400, problem.Value.Code, problem.Value.Message);
            return;
        }

        // Шаг 2: второй TTL — внутри самого SafeActionManager.
        var status = _safeActions.Confirm() switch
        {
            ConfirmOutcome.Executed => "executed",
            ConfirmOutcome.Failed => "failed",
            _ => null, // Expired / NoPending
        };

        if (status is null)
        {
            await SendErrorAsync(response, 400, "TTL_EXPIRED", "Срок подтверждения истёк — запросите действие заново.");
            return;
        }

        await SendJsonAsync(response, 200, new { Status = status, Action = action });
    }

    private ProcessInfo? FindProcess(int pid) =>
        _processes is null
            ? null
            : _processes.GetProcesses().FirstOrDefault(p => p.Id == pid);

    /// <summary>
    /// Строка списка процессов: поля ProcessInfo + флаг защиты.
    /// CPU не отдаём намеренно: ни C#, ни Python-сервис процессов его не
    /// измеряют — не показываем в UI то, чего нет (§5 плана).
    /// </summary>
    private static object ProcessPayload(ProcessInfo info) => new
    {
        Pid = info.Id,
        Name = info.Name,
        MemoryMb = info.MemoryMb,
        Responding = info.Responding,
        Protected = ProcessService.IsProtected(info.Name),
    };

    private static bool IsEmptyObject(JsonDocument payload)
    {
        if (payload.RootElement.ValueKind != JsonValueKind.Object)
            return false;

        var properties = payload.RootElement.EnumerateObject();
        return !properties.MoveNext();
    }

    /// <summary>Читает тело как JSON-объект; null = ответ об ошибке уже отправлен.</summary>
    private static async Task<JsonDocument?> ReadRequestBodyObjectAsync(
        HttpListenerRequest request,
        HttpListenerResponse response)
    {
        var payload = await ReadJsonObjectAsync(request, response);

        if (payload is null)
            return null;

        if (payload.RootElement.ValueKind != JsonValueKind.Object)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Ожидался JSON-объект в теле запроса.");
            return null;
        }

        return payload;
    }

    /// <summary>Подтверждение опасного действия: ровно {confirm, ttlToken}.</summary>
    private static string? ValidateTtlPayload(JsonElement payload, string expected)
    {
        foreach (var property in payload.EnumerateObject())
        {
            if (property.Name != "confirm" && property.Name != "ttlToken")
                return $"Неизвестный ключ: «{property.Name}».";
        }

        if (!payload.TryGetProperty("confirm", out var confirm))
            return "Отсутствует обязательный ключ: «confirm».";

        if (confirm.ValueKind != JsonValueKind.String || !string.Equals(confirm.GetString(), expected, StringComparison.Ordinal))
            return $"Ожидалось подтверждение confirm = \"{expected}\".";

        if (!payload.TryGetProperty("ttlToken", out var token))
            return "Отсутствует обязательный ключ: «ttlToken».";

        if (token.ValueKind != JsonValueKind.String)
            return "Ключ «ttlToken» должен быть строкой.";

        return null;
    }

    /// <summary>Одноразовый токен подтверждения; живёт не дольше TtlSeconds.</summary>
    private string IssueChallenge(string action)
    {
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)).ToLowerInvariant();

        lock (_challengeLock)
        {
            _challenge = (token, action, Environment.TickCount64);
        }

        return token;
    }

    /// <summary>Проверяет и гасит токен. null — годен; иначе (код, сообщение).</summary>
    private (string Code, string Message)? ConsumeChallenge(string? token, string action)
    {
        if (token is null || token.Length != 32 || !token.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f'))
            return ("VALIDATION_ERROR", "Некорректный ttlToken.");

        lock (_challengeLock)
        {
            var challenge = _challenge;
            _challenge = null; // гасим в любом случае: токен одноразовый

            if (challenge is null || !string.Equals(challenge.Value.Token, token, StringComparison.Ordinal))
                return ("TTL_EXPIRED", "Нет действия, ожидающего подтверждения.");

            if (!string.Equals(challenge.Value.Action, action, StringComparison.Ordinal))
                return ("TTL_EXPIRED", "Подтверждение относится к другому действию.");

            if (Environment.TickCount64 - challenge.Value.IssuedAt > TtlSeconds * 1000L)
                return ("TTL_EXPIRED", "Срок подтверждения истёк — запросите действие заново.");
        }

        return null;
    }

    private static object ToMemoryPayload(MemoryItem item) => new
    {
        Id = item.Id,
        Key = item.Key,
        Value = item.Value,
        Category = item.Category,
        CreatedAt = item.CreatedAt.ToString("O"),
    };

    /// <summary>Читает тело как JSON-объект; null = ответ об ошибке уже отправлен.</summary>
    private static async Task<JsonDocument?> ReadJsonObjectAsync(HttpListenerRequest request, HttpListenerResponse response)
    {
        if (request.ContentLength64 > MaxBodyBytes)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Недопустимый размер тела запроса.");
            return null;
        }

        string body;

        using (var reader = new StreamReader(request.InputStream, Encoding.UTF8))
        {
            body = await reader.ReadToEndAsync();
        }

        try
        {
            return JsonDocument.Parse(body);
        }
        catch (JsonException)
        {
            await SendErrorAsync(response, 400, "VALIDATION_ERROR", "Тело запроса не является корректным JSON.");
            return null;
        }
    }

    private static bool TryReadIntQuery(
        HttpListenerRequest request,
        string name,
        int defaultValue,
        int minimum,
        int maximum,
        out int value,
        out string? error)
    {
        value = defaultValue;
        error = null;

        var raw = request.QueryString[name];

        if (string.IsNullOrEmpty(raw))
            return true;

        if (!int.TryParse(raw, out var parsed))
        {
            error = $"Параметр «{name}» должен быть целым числом.";
            return false;
        }

        if (parsed < minimum || parsed > maximum)
        {
            error = $"Параметр «{name}» должен быть в диапазоне {minimum}…{maximum}.";
            return false;
        }

        value = parsed;
        return true;
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
