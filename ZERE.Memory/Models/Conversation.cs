namespace ZERE.Memory.Models;

public class Conversation
{
    public long Id { get; set; }
    public string UserMessage { get; set; } = "";
    public string ZereResponse { get; set; } = "";
    public DateTime Timestamp { get; set; }
}
