using System.Text;

namespace JARVIS.Core.AI;

public class PromptBuilder
{
    private readonly StringBuilder _builder = new();

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
            _builder.AppendLine("=== ПАМЯТЬ ПОЛЬЗОВАТЕЛЯ ===");
            _builder.AppendLine(memory);
            _builder.AppendLine();
        }

        return this;
    }

    public PromptBuilder History(string history)
    {
        if (!string.IsNullOrWhiteSpace(history))
        {
            _builder.AppendLine("=== ПОСЛЕДНИЙ ДИАЛОГ ===");
            _builder.AppendLine(history);
            _builder.AppendLine();
        }

        return this;
    }

    public PromptBuilder UserMessage(string message)
    {
        _builder.AppendLine("=== СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ ===");
        _builder.AppendLine(message);
        _builder.AppendLine();
        _builder.AppendLine("=== ОТВЕТ АССИСТЕНТА ===");

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