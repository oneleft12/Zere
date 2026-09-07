using JARVIS.Memory.Models;

namespace JARVIS.Memory.Database;

public class MemoryRepository
{
    private readonly MemoryDatabase _database = new();

    public void Remember(string key, string value, string category = "User")
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        """
        INSERT INTO Memories(Key, Value, Category, CreatedAt)
        VALUES($key,$value,$category,$time)
        ON CONFLICT(Key)
        DO UPDATE SET
            Value = excluded.Value,
            Category = excluded.Category;
        """;

        command.Parameters.AddWithValue("$key", key.ToLower());
        command.Parameters.AddWithValue("$value", value);
        command.Parameters.AddWithValue("$category", category);
        command.Parameters.AddWithValue("$time", DateTime.Now.ToString("O"));

        command.ExecuteNonQuery();
    }

    public bool Forget(string key)
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        """
        DELETE FROM Memories WHERE Key=$key
        """;

        command.Parameters.AddWithValue("$key", key.ToLower());

        return command.ExecuteNonQuery() > 0;
    }

    public List<MemoryItem> GetAll()
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        """
        SELECT Id, Key, Value, Category, CreatedAt
        FROM Memories
        ORDER BY Category, Key
        """;

        var reader = command.ExecuteReader();

        var list = new List<MemoryItem>();

        while (reader.Read())
        {
            list.Add(new MemoryItem
            {
                Id = reader.GetInt64(0),
                Key = reader.GetString(1),
                Value = reader.GetString(2),
                Category = reader.GetString(3),
                CreatedAt = DateTime.Parse(reader.GetString(4))
            });
        }

        return list;
    }
    public void Clear()
    {
    using var connection = _database.CreateConnection();

    connection.Open();

    var command = connection.CreateCommand();

    command.CommandText = "DELETE FROM Memories";

    command.ExecuteNonQuery();
    }
    public MemoryItem? Find(string key)
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        """
        SELECT Id, Key, Value, Category, CreatedAt
        FROM Memories
        WHERE lower(Key)=lower($key)
        """;

        command.Parameters.AddWithValue("$key", key.ToLower());

        var reader = command.ExecuteReader();

        if (!reader.Read())
            return null;

        return new MemoryItem
        {
            Id = reader.GetInt64(0),
            Key = reader.GetString(1),
            Value = reader.GetString(2),
            Category = reader.GetString(3),
            CreatedAt = DateTime.Parse(reader.GetString(4))
        };
    }
}