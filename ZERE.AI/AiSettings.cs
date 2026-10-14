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

    public const string DefaultLocalModel = "t-tech/T-lite-it-2.1:q4_K_M";
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
        // OpenAI-совместимый Chat Completions: https://opencode.ai/zen/go/v1
        // Модели Responses/Anthropic (grok, gpt-*-luna, minimax, qwen) здесь
        // не подходят — выбран glm как дешёвый и с большим месячным лимитом.
        new("opencode-go", "OpenCode Go (подписка)", "https://opencode.ai/zen/go/v1",
            "glm-5.3-flash", "https://opencode.ai/console"),
        new("custom", "Свой OpenAI-совместимый сервер", "", "", ""),
    ];

    public static readonly string[] ProviderIds = Presets.Select(p => p.Id).ToArray();

    /// <summary>
    /// Локальные модели: порядок — от «русский важнее всего» к «лишь бы влезло».
    /// У малых моделей русского почти нет (docs/LOCAL_MODELS_RESEARCH.md, §7),
    /// поэтому Qwen2.5 (2024) заменена на Qwen3.5 и русско-ориентированный T-lite.
    /// </summary>
    public static readonly LocalModelOption[] LocalModelSuggestions =
    [
        new("t-tech/T-lite-it-2.1:q4_K_M", "T-lite 2.1 (8B) — лучший русский, 16 ГБ", "medium", "~5 ГБ"),
        new("qwen3.5:4b-q4_K_M", "qwen3.5:4b — быстрый, русский нормальный, 8–16 ГБ", "medium", "~3.3 ГБ"),
        new("qwen3.5:2b-q4_K_M", "qwen3.5:2b — слабый ПК, 8 ГБ", "light", "~1.9 ГБ"),
        new("qwen3.5:0.8b", "qwen3.5:0.8b — очень слабый ПК, 4 ГБ", "tiny", "~1.2 ГБ"),
        new("qwen3.5:9b-q4_K_M", "qwen3.5:9b — максимум качества Qwen, 16 ГБ", "medium", "~6.6 ГБ"),
        new("qwen2.5:0.5b", "qwen2.5:0.5b — последний резерв, 4 ГБ (русский слабый)", "tiny", "~0.4 ГБ"),
    ];

    [JsonPropertyName("mode")]
    public string Mode { get; set; } = ModeAuto;

    [JsonPropertyName("cloud_provider")]
    public string CloudProvider { get; set; } = "openai";

    [JsonPropertyName("cloud_base_url")]
    public string CloudBaseUrl { get; set; } = "https://api.openai.com/v1";

    [JsonPropertyName("cloud_model")]
    public string CloudModel { get; set; } = "gpt-4o-mini";

    /// <summary>Секрет: на диск в config/ai.json, наружу — только маска.</summary>
    [JsonPropertyName("cloud_api_key")]
    public string CloudApiKey { get; set; } = "";

    [JsonPropertyName("cloud_key_status")]
    public string CloudKeyStatus { get; set; } = KeyUnknown;

    [JsonPropertyName("cloud_key_checked_at")]
    public string CloudKeyCheckedAt { get; set; } = "";

    [JsonPropertyName("local_base_url")]
    public string LocalBaseUrl { get; set; } = DefaultLocalBaseUrl;

    [JsonPropertyName("local_model")]
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

    /// <summary>
    /// Читает config/ai.json: ключи принимаются и в snake_case (Python-редакция,
    /// текущий формат), и в camelCase (файлы старых сборок C#).
    ///
    /// Раньше редакции писали разный формат ключей, и настройки друг друга
    /// молча игнорировались — облачная модель и ключ сбрасывались на значения
    /// по умолчанию (панель показывала «gpt-4o-mini» вместо выбранной модели).
    /// </summary>
    public static AiSettings Load(bool applyEnv = true)
    {
        AiSettings settings;

        try
        {
            var path = ConfigPath;

            if (File.Exists(path))
            {
                var text = File.ReadAllText(path);
                settings = ParseFile(text);
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

    /// <summary>Разбор файла: ключи приводятся к snake_case, null-значения пропускаются.</summary>
    private static AiSettings ParseFile(string text)
    {
        using var document = JsonDocument.Parse(text);
        var normalized = new Dictionary<string, JsonElement>(StringComparer.Ordinal);

        if (document.RootElement.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in document.RootElement.EnumerateObject())
            {
                if (property.Value.ValueKind == JsonValueKind.Null)
                    continue;

                normalized[FileName(property.Name)] = property.Value;
            }
        }

        var json = JsonSerializer.Serialize(normalized);

        return JsonSerializer.Deserialize<AiSettings>(json, ReadOptions) ?? new AiSettings();
    }

    /// <summary>camelCase → snake_case («cloudModel» → «cloud_model»).</summary>
    private static string FileName(string name)
    {
        if (name.Contains('_'))
            return name.ToLowerInvariant();

        var builder = new System.Text.StringBuilder(name.Length + 4);

        for (var index = 0; index < name.Length; index++)
        {
            var symbol = name[index];

            if (char.IsUpper(symbol))
            {
                if (index > 0)
                    builder.Append('_');

                builder.Append(char.ToLowerInvariant(symbol));
            }
            else
            {
                builder.Append(symbol);
            }
        }

        return builder.ToString();
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

        // Секрет: сужаем права до владельца ещё до публикации файла на месте.
        // Раньше на Windows блок пропускался, и ключ наследовал права папки
        // (BUILTIN\Пользователи: Read, Authenticated Users: Modify) — см.
        // SecretFileAccess и паритет zere/core/security/file_access.py.
        SecretFileAccess.RestrictToOwner(tmp);

        File.Move(tmp, path, overwrite: true);

        SecretFileAccess.RestrictToOwner(path);
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
