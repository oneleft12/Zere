using System.Text;

namespace JARVIS.Core.AI;

public class PromptBuilder
{
    private readonly StringBuilder _builder = new();

    public PromptBuilder SystemPrompt(string assistantName)
    {
        _builder.AppendLine($"Ты {assistantName} — персональный AI-ассистент пользователя.");
        _builder.AppendLine("Ты помогаешь с Windows, программированием, файлами и проектами.");
        _builder.AppendLine("Отвечай только на русском языке.");
        _builder.AppendLine("Если информация есть в памяти пользователя — используй её.");
        _builder.AppendLine("Не выдумывай факты.");
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
}