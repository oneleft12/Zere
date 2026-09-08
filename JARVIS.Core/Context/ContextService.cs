namespace JARVIS.Core.Context;

public static class ContextService
{
    public static ContextMemory Current { get; } = new();
}