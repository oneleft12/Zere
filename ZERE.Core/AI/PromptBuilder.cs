using System.Text;

namespace ZERE.Core.AI;

public class PromptBuilder
{
    private readonly StringBuilder _builder = new();
    private readonly string _memoryLabel;
    private readonly string _historyLabel;
    private readonly string _userLabel;
    private readonly string _answerLabel;

    // Заголовки блоков промпта: при language=en английские, иначе модель
    // получает правило «answer only in English», но русские заголовки в самом
    // промпте тянули ответ обратно в русский (паритет с Python).
    public PromptBuilder(string language = "ru")
    {
        var english = string.Equals(language, "en", StringComparison.OrdinalIgnoreCase);

        _memoryLabel = english ? "=== USER MEMORY ===" : "=== ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ ===";
        _historyLabel = english ? "=== LAST DIALOG ===" : "=== ПОСЛЕДНИЙ ДИАЛОГ ===";
        _userLabel = english ? "=== USER MESSAGE ===" : "=== СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ ===";
        _answerLabel = english ? "=== ASSISTANT ANSWER ===" : "=== ОТВЕТ АССИСТЕНТА ===";
    }

    public PromptBuilder SystemPrompt(string systemPrompt)
    {
        _builder.AppendLine(systemPrompt);
        _builder.AppendLine();

        return this;
    }

    public PromptBuilder Memory(string memory)
    {
        if (!string.IsNullOrWhiteSpace(memory))
        {
            _builder.AppendLine(_memoryLabel);
            _builder.AppendLine(memory);
            _builder.AppendLine();
        }

        return this;
    }

    public PromptBuilder History(string history)
    {
        if (!string.IsNullOrWhiteSpace(history))
        {
            _builder.AppendLine(_historyLabel);
            _builder.AppendLine(history);
            _builder.AppendLine();
        }

        return this;
    }

    public PromptBuilder UserMessage(string message)
    {
        _builder.AppendLine(_userLabel);
        _builder.AppendLine(message);
        _builder.AppendLine();
        _builder.AppendLine(_answerLabel);

        return this;
    }

    public string Build()
    {
        return _builder.ToString();
    }

    public void Reset()
    {
        _builder.Clear();
    }
}