namespace JARVIS.Core.Context;

public class ContextMemory
{
    private readonly List<ContextItem> _items = new();
    private readonly object _lock = new();

    public void Remember(ContextType type, string name, string value)
    {
        lock (_lock)
        {
            _items.Insert(0, new ContextItem
            {
                Type = type,
                Name = name,
                Value = value,
                Time = DateTime.Now
            });

            if (_items.Count > 10)
                _items.RemoveAt(_items.Count - 1);
        }
    }

    public ContextItem? Last(ContextType type)
    {
        lock (_lock)
        {
            return _items.FirstOrDefault(i => i.Type == type);
        }
    }

    public void Clear()
    {
        lock (_lock)
        {
            _items.Clear();
        }
    }

    public List<ContextItem> GetAll()
    {
        lock (_lock)
        {
            return _items.ToList();
        }
    }
}
