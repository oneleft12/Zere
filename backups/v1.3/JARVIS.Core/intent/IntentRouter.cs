namespace JARVIS.Core.Intent;

public class IntentRouter
{
    private readonly string[] _openWords =
    {
        "открой",
        "запусти",
        "включи",
        "запустить",
        "мне нужен",
        "нужен"
    };

    public IntentResult Parse(string message)
    {
        var lower = message.ToLower().Trim();

        foreach (var word in _openWords)
        {
            if (lower.Contains(word))
            {
                var appName = lower.Replace(word, "").Trim();

                return new IntentResult
                {
                    Type = IntentType.OpenApplication,
                    Value = appName
                };
            }
        }

        return new IntentResult
        {
            Type = IntentType.Chat,
            Value = message
        };
    }
}