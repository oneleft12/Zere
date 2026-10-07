using System.Text.RegularExpressions;

namespace ZERE.AI;

/// <summary>
/// Нормализованная ошибка ИИ: код контракта + понятный текст
/// (docs/AI_PROVIDERS.md, §7). Используется панелью для ответа
/// <c>{code, message}</c> с нужным HTTP-статусом.
/// </summary>
public sealed class AiError : Exception
{
    public string Code { get; }

    public int Status { get; }

    public AiError(string code, string message, int status = 400)
        : base(message)
    {
        Code = code;
        Status = status;
    }
}

/// <summary>
/// Коды и тексты ошибок ИИ (требование 11 задачи) — единый источник для
/// облачной и локальной частей.
/// </summary>
public static class AiErrorCodes
{
    public const string KeyInvalid = "AI_KEY_INVALID";
    public const string NoCredits = "AI_NO_CREDITS";
    public const string RateLimit = "AI_RATE_LIMIT";
    public const string ModelUnavailable = "AI_MODEL_UNAVAILABLE";
    public const string Network = "AI_NETWORK";
    public const string ProviderError = "AI_PROVIDER_ERROR";
    public const string EmptyAnswer = "AI_EMPTY_ANSWER";
    public const string LocalServerDown = "AI_LOCAL_SERVER_DOWN";
    public const string LocalModelMissing = "AI_LOCAL_MODEL_MISSING";
    public const string PullUnsupported = "AI_PULL_UNSUPPORTED";
    public const string Validation = "AI_VALIDATION";

    public const string MessageKeyInvalid = "Неверный API-ключ";
    public const string MessageNoCredits = "На балансе нет средств";
    public const string MessageRateLimit = "Превышен лимит запросов";
    public const string MessageModelUnavailable = "Модель недоступна";
    public const string MessageNetwork =
        "Не удалось подключиться к облачному API — проверьте интернет и Base URL";
    public const string MessageProviderError = "Облачный провайдер вернул ошибку";
    public const string MessageEmptyAnswer = "Провайдер вернул пустой ответ";
    public const string MessageLocalServerDown = "Локальный сервер не запущен";
    public const string MessageLocalModelMissing = "Локальная модель не загружена";
}

/// <summary>
/// Маскирование секретов на выходе логов.
///
/// Ключ API не должен попасть в logs/ ни при каких обстоятельствах, даже
/// если он окажется внутри текста исключения (HttpClient кладёт в него URL
/// и заголовки). Паритет с redact_secrets в zere/core/logging/log_service.py.
/// </summary>
public static class SecretRedactor
{
    private static readonly (Regex Pattern, string Replacement)[] Patterns =
    [
        (new Regex(@"\bsk-[A-Za-z0-9_\-]{6,}", RegexOptions.Compiled), "***"),
        (new Regex(@"\bgsk_[A-Za-z0-9]{6,}", RegexOptions.Compiled), "***"),
        (new Regex(@"\bAIza[A-Za-z0-9_\-]{10,}", RegexOptions.Compiled), "***"),
        (new Regex(@"\bxai-[A-Za-z0-9]{6,}", RegexOptions.Compiled), "***"),
        (new Regex(@"(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})", RegexOptions.Compiled), "$1***"),
        (
            new Regex(
                "(?i)([\"']?(?:api[_-]?key|apikey|authorization)[\"']?\\s*[:=]\\s*[\"'])([^\"']{8,})([\"'])",
                RegexOptions.Compiled),
            "$1***$3"
        ),
    ];

    public static string Redact(string? text)
    {
        if (string.IsNullOrEmpty(text))
            return text ?? string.Empty;

        var result = text;

        foreach (var (pattern, replacement) in Patterns)
            result = pattern.Replace(result, replacement);

        return result;
    }
}
