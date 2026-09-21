namespace JARVIS.Core.Context;

public class ContextService
{
    private readonly ContextMemory _memory = new();

    public ContextMemory Current => _memory;
}