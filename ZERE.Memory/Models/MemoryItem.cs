namespace ZERE.Memory.Models;

public class MemoryItem
{
    public long Id { get; set; }
    public string Key { get; set; } = "";
    public string Value { get; set; } = "";
    public string Category { get; set; } = "";
    public DateTime CreatedAt { get; set; }
}
