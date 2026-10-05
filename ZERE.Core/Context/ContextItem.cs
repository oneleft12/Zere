namespace ZERE.Core.Context;

public class ContextItem
{
    public ContextType Type { get; set; }

    public string Name { get; set; } = "";

    public string Value { get; set; } = "";

    public DateTime Time { get; set; } = DateTime.UtcNow;
}