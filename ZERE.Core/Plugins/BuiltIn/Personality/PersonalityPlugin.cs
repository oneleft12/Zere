using ZERE.Core.Plugins.Interfaces;

namespace ZERE.Core.Plugins.BuiltIn.Personality;

public class PersonalityPlugin : BasePlugin, IPersonalityPlugin
{
    public override string Id => "personality";
    public override string Name => "Личность ZERE";
    public override string Description => "Встроенные стили общения ассистента";
    public override string Version => "1.0.0";
    public override string Author => "ZERE";
    public override PluginType Type => PluginType.Personality;

    private PersonalityStyle _currentStyle = PersonalityStyle.Friendly;

    private readonly Dictionary<PersonalityStyle, string> _prompts = new()
    {
        [PersonalityStyle.Friendly] = """
            Ты — ZERE, дружелюбный AI-ассистент.
            Общайся тепло, изредка используй смайлики.
            Будь как друг — помогай с радостью.
            Говори просто и понятно.
            """,

        [PersonalityStyle.Formal] = """
            Ты — ZERE, официальный AI-ассистент.
            Общайся строго, профессионально.
            Используй вежливую форму общения.
            Не используй смайлики.
            """,

        [PersonalityStyle.Sarcastic] = """
            Ты — ZERE, саркастичный AI-ассистент.
            Отвечай с умным юмором и иронией.
            Поддразнивай пользователя, но оставайся полезным.
            Будь как умный друг, который шутит.
            """,

        [PersonalityStyle.Professional] = """
            Ты — ZERE, профессиональный AI-ассистент.
            Общайся по делу, без лишних слов.
            Давай точные и структурированные ответы.
            Фокусируйся на эффективности.
            """,

        [PersonalityStyle.Casual] = """
            Ты — ZERE, неформальный AI-ассистент.
            Общайся как с другом, на "ты".
            Используй разговорные фразы.
            Будь расслабленным и весёлым.
            """,

        [PersonalityStyle.Custom] = """
            Ты — ZERE, настроенный ассистент.
            Следуй кастомным инструкциям из конфигурации.
            """
    };

    private readonly Dictionary<PersonalityStyle, float> _temperatures = new()
    {
        [PersonalityStyle.Friendly] = 0.7f,
        [PersonalityStyle.Formal] = 0.3f,
        [PersonalityStyle.Sarcastic] = 0.9f,
        [PersonalityStyle.Professional] = 0.4f,
        [PersonalityStyle.Casual] = 0.8f,
        [PersonalityStyle.Custom] = 0.7f
    };

    public string SystemPrompt => _prompts[_currentStyle];
    public float Temperature => _temperatures[_currentStyle];
    public PersonalityStyle Style => _currentStyle;

    public string[] GetAvailableStyles()
    {
        return Enum.GetNames<PersonalityStyle>()
            .Where(s => s != "Custom")
            .ToArray();
    }

    public void SetStyle(string styleName)
    {
        if (Enum.TryParse<PersonalityStyle>(styleName, true, out var style))
        {
            _currentStyle = style;
            Console.WriteLine($"[Personality] Стиль изменён на: {styleName}");
        }
        else
        {
            Console.WriteLine($"[Personality] Неизвестный стиль: {styleName}");
        }
    }

    public void SetInitialStyle(string styleName)
    {
        if (Enum.TryParse<PersonalityStyle>(styleName, true, out var style))
        {
            _currentStyle = style;
        }
    }

    public void SetCustomPrompt(string prompt)
    {
        _prompts[PersonalityStyle.Custom] = prompt;
        _currentStyle = PersonalityStyle.Custom;
    }

    public override void Initialize()
    {
        Console.WriteLine($"[Personality] Инициализирован. Текущий стиль: {_currentStyle}");
    }

    public override void Dispose()
    {
        Console.WriteLine("[Personality] Выгружен.");
    }
}
