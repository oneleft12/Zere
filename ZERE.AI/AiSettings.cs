using System.Text.Json;
using System.Text.Json.Serialization;

namespace ZERE.AI;

/// <summary>Пресет OpenAI-совместимого облачного провайдера.</summary>
public sealed record ProviderPreset(
    string Id,
    string Label,
    string BaseUrl,
    string Model,
    string DocsUrl);

/// <summary>Лёгкая локальная модель для слабого ПК.</summary>
public sealed record LocalModelOption(string Id, string Label, string Tier, string SizeHint);

/// <summary>
/// Настройки выбора ИИ: облачный ключ пользователя или локальная модель.
///
/// Файл config/ai.json (в .gitignore) — единственное место, где лежит ключ.
/// Ключ используется только на бэкенде и никогда не отдаётся клиенту:
/// наружу уходит маска вида «sk-...abcd» (требования безопасности задачи).
///
/// Приоритет источников ключа:
/// 1. config/ai.json — ключ пользователя (вводится в панели, удаляется кнопкой);
/// 2. окружение сервера — ключ владельца (ZERE_CLOUD_API_KEY), только для его
///    аккаунта: обычный пользователь его не видит и не может им пользоваться,
///    если у него есть свой ключ.
///
/// Паритет с Python-редакцией (zere/ai/ai_settings.py).
/// </summary>
public sealed class AiSettings
{
    public const string ModeAuto = "auto";
    public const string ModeCloud = "cloud";
    public const string ModeLocal = "local";

    public static readonly string[] Modes = [ModeAuto, ModeCloud, ModeLocal];

    public const string KeyUnknown = "unknown";
    public const string KeyOk = "ok";
    public const string KeyInvalid = "invalid";

    public const string SourceNone = "none";
    public const string SourceUser = "user";
    public const string SourceOwner = "owner";

    public const string DefaultLocalModel = "qwen3.5:2b";
    public const string DefaultLocalBaseUrl = "http://127.0.0.1:11434/v1";

    /// <summary>Переменные окружения владельца сервера.</summary>
    public const string EnvMode = "ZERE_AI_MODE";
    public const string EnvCloudApiKey = "ZERE_CLOUD_API_KEY";
    public const string EnvCloudBaseUrl = "ZERE_CLOUD_BASE_URL";
    public const string EnvCloudModel = "ZERE_CLOUD_MODEL";
    public const string EnvCloudProvider = "ZERE_CLOUD_PROVIDER";
    public const string EnvLocalBaseUrl = "ZERE_LOCAL_BASE_URL";
    public const string EnvLocalModel = "ZERE_LOCAL_MODEL";

    /// <summary>Готовые адреса OpenAI-совместимых облачных API.</summary>
    public static readonly ProviderPreset[] Presets =
    [
        new("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini",
            "https://platform.openai.com/api-keys"),
        new("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat",
            "https://platform.deepseek.com/api_keys"),
        new("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4o-mini",
            "https://openrouter.ai/keys"),
        new("groq", "Groq", "https://api.groq.com/openai/v1", "llama-3.1-8b-instant",
            "https://console.groq.com/keys"),
        new("custom", "Свой OpenAI-совместимый сервер", "", "", ""),
    ];

    public static readonly string[] ProviderIds = Presets.Select(p => p.Id).ToArray();

    /// <summary>
    /// Лёгкие модели для слабых ПК: по умолчанию ничего тяжёлого
    /// (0.5B–1.5B для очень слабых, 3B для средних).
    /// </summary>
    public static readonly LocalModelOption[] LocalModelSuggestions =
    [
        new("qwen3.5:2b", "qwen3.5:2b — по умолчанию ZERE", "light", "~1.5 ГБ"),
        new("qwen2.5:0.5b", "qwen2.5:0.5b — очень слабый ПК", "tiny", "~0.4 ГБ"),
        new("qwen2.5:1.5b", "qwen2.5:1.5b — слабый ПК", "light", "~1 ГБ"),
        new("qwen2.5:3b", "qwen2.5:3b — средний ПК", "tiny", "~2 ГБ"),
    ];

    [JsonPropertyName("mode")]
    public string Mode { get; set; } = ModeAuto;

    [JsonPropertyName("cloudProvider")]
    public string CloudProvider { get; set; } = "openai";

    [JsonPropertyName("cloudBaseUrl")]
    public string CloudBaseUrl { get; set; } = "https://api.openai.com/v1";

    [JsonPropertyName("cloudModel")]
    public string CloudModel { get; set; } = "gpt-4o-mini";

    /// <summary>Секрет: на диск в config/ai.json, наружу — только маска.</summary>
    [JsonPropertyName("cloudApiKey")]
    public string CloudApiKey { get; set; } = "";

    [JsonPropertyName("cloudKeyStatus")]
    public string CloudKeyStatus { get; set; } = KeyUnknown;

    [JsonPropertyName("cloudKeyCheckedAt")]
    public string CloudKeyCheckedAt { get; set; } = "";

    [JsonPropertyName("localBaseUrl")]
    public string LocalBaseUrl { get; set; } = DefaultLocalBaseUrl;

    [JsonPropertyName("localModel")]
    public string LocalModel { get; set; } = DefaultLocalModel;

    private static readonly JsonSerializerOptions WriteOptions = new()
    {
        WriteIndented = true,
    };

    private static readonly JsonSerializerOptions ReadOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    /// <summary>Путь к файлу настроек ИИ (рядом с config.json).</summary>
    public static string ConfigPath => Path.Combine(
        Directory.GetCurrentDirectory(),
        "config",
        "ai.json");

    public static AiSettings Load(bool applyEnv = true)
    {
        AiSettings settings;

        try
        {
            var path = ConfigPath;

            if (File.Exists(path))
            {
                var text = File.ReadAllText(path);
                settings = JsonSerializer.Deserialize<AiSettings>(text, ReadOptions) ?? new AiSettings();
            }
            else
            {
                settings = new AiSettings();
            }
        }
        catch (Exception ex) when (ex is IOException or JsonException or UnauthorizedAccessException)
        {
            // Битый/недоступный файл не должен валить старт: значения по умолчанию.
            settings = new AiSettings();
        }

        if (applyEnv)
            settings.ApplyEnv();

        return settings;
    }

    /// <summary>Переменные окружения владельца сервера (перекрывают файл).</summary>
    public void ApplyEnv()
    {
        var mode = Environment.GetEnvironmentVariable(EnvMode)?.Trim().ToLowerInvariant();

        if (mode is not null && Modes.Contains(mode, StringComparer.Ordinal))
            Mode = mode;

        var provider = Environment.GetEnvironmentVariable(EnvCloudProvider)?.Trim().ToLowerInvariant();

        if (provider is not null && ProviderIds.Contains(provider, StringComparer.Ordinal))
            CloudProvider = provider;

        var baseUrl = Environment.GetEnvironmentVariable(EnvCloudBaseUrl)?.Trim();

        if (!string.IsNullOrEmpty(baseUrl))
            CloudBaseUrl = baseUrl;

        var model = Environment.GetEnvironmentVariable(EnvCloudModel)?.Trim();

        if (!string.IsNullOrEmpty(model))
            CloudModel = model;

        var localBase = Environment.GetEnvironmentVariable(EnvLocalBaseUrl)?.Trim();

        if (!string.IsNullOrEmpty(localBase))
            LocalBaseUrl = localBase;

        var localModel = Environment.GetEnvironmentVariable(EnvLocalModel)?.Trim();

        if (!string.IsNullOrEmpty(localModel))
            LocalModel = localModel;
    }

    /// <summary>Атомарная запись файла настроек (временный файл + переименование).</summary>
    public void Save()
    {
        var path = ConfigPath;
        var directory = Path.GetDirectoryName(path);

        if (directory is not null)
            Directory.CreateDirectory(directory);

        var tmp = path + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(this, WriteOptions));

        if (!OperatingSystem.IsWindows())
        {
            try
            {
                File.SetUnixFileMode(tmp, UnixFileMode.UserRead | UnixFileMode.UserWrite);
            }
            catch (Exception)
            {
                // Чужая ФС: права не критичны, файл всё равно вне git
            }
        }

        File.Move(tmp, path, overwrite: true);
    }

    /// <summary>Маска ключа для интерфейса: «sk-...abcd».</summary>
    public static string MaskKey(string? key)
    {
        if (string.IsNullOrWhiteSpace(key))
            return "";

        var trimmed = key.Trim();

        if (trimmed.Length <= 8)
            return "***";

        return $"{trimmed[..3]}...{trimmed[^4..]}";
    }

    public static string EnvApiKey() =>
        Environment.GetEnvironmentVariable(EnvCloudApiKey)?.Trim() ?? "";

    public string UserApiKey() => CloudApiKey?.Trim() ?? "";

    /// <summary>Ключ пользователя важнее ключа владельца.</summary>
    public (string Key, string Source) ActiveKey()
    {
        var userKey = UserApiKey();

        if (!string.IsNullOrEmpty(userKey))
            return (userKey, SourceUser);

        var ownerKey = EnvApiKey();

        if (!string.IsNullOrEmpty(ownerKey))
            return (ownerKey, SourceOwner);

        return ("", SourceNone);
    }

    public bool HasKey() => !string.IsNullOrEmpty(ActiveKey().Key);

    /// <summary>Ключ есть и не помечен как нерабочий.</summary>
    public bool HasWorkingKey() =>
        HasKey() && !string.Equals(CloudKeyStatus, KeyInvalid, StringComparison.Ordinal);

    public object CloudPublic()
    {
        var (key, source) = ActiveKey();

        return new
        {
            provider = CloudProvider,
            baseUrl = CloudBaseUrl,
            model = CloudModel,
            keySaved = !string.IsNullOrEmpty(key),
            keySource = source,
            keyMask = MaskKey(key),
            keyStatus = string.IsNullOrEmpty(key) ? KeyUnknown : CloudKeyStatus,
            keyCheckedAt = string.IsNullOrEmpty(CloudKeyCheckedAt) ? null : CloudKeyCheckedAt,
        };
    }

    public object LocalPublic() => new
    {
        baseUrl = LocalBaseUrl,
        model = LocalModel,
        suggestions = LocalModelSuggestions,
    };

    /// <summary>Человекочитаемый путь файла настроек (для UI).</summary>
    public static string DescribePath()
    {
        var path = ConfigPath;
        var root = Directory.GetCurrentDirectory();

        return path.StartsWith(root, StringComparison.Ordinal)
            ? Path.GetRelativePath(root, path).Replace('\\', '/')
            : path;
    }
}
