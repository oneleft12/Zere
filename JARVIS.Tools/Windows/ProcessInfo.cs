namespace JARVIS.Tools.Windows.Processes;

public class ProcessInfo
{
    public int Id { get; set; }

    public string Name { get; set; } = "";

    public double MemoryMb { get; set; }

    public bool Responding { get; set; }
}