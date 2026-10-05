using ZERE.Memory.Models;

namespace ZERE.Memory.Database;

public class ConversationRepository
{
    private readonly MemoryDatabase _database;

    public ConversationRepository(MemoryDatabase database)
    {
        _database = database;
    }

    /// <summary>Колонка ответа: ZereResponse, либо JarvisResponse в старой базе.</summary>
    private string ResponseColumn => _database.ResponseColumn;

    public void Save(string userMessage, string zereResponse)
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        $"""
        INSERT INTO Conversations
        (UserMessage, {ResponseColumn}, Timestamp)
        VALUES ($user, $zere, $time)
        """;

        command.Parameters.AddWithValue("$user", userMessage);
        command.Parameters.AddWithValue("$zere", zereResponse);
        command.Parameters.AddWithValue("$time", DateTime.Now.ToString("O"));

        command.ExecuteNonQuery();
    }

    public void ClearHistory()
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText = "DELETE FROM Conversations";

        command.ExecuteNonQuery();
    }

    public List<Conversation> GetLast(int count)
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        $"""
        SELECT Id, UserMessage, {ResponseColumn}, Timestamp
        FROM Conversations
        ORDER BY Id DESC
        LIMIT $count
        """;

        command.Parameters.AddWithValue("$count", count);

        using var reader = command.ExecuteReader();

        var conversations = new List<Conversation>();

        while (reader.Read())
        {
            conversations.Add(new Conversation
            {
                Id = reader.GetInt64(0),
                UserMessage = reader.GetString(1),
                ZereResponse = reader.GetString(2),
                Timestamp = DateTime.Parse(reader.GetString(3), System.Globalization.CultureInfo.InvariantCulture)
            });
        }

        return conversations;
    }

    /// <summary>Всего записей истории (для пагинации /api/history).</summary>
    /// <param name="search">Подстрока поиска по вопросу и ответу (пусто — все).</param>
    public long Count(string search = "")
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        if (string.IsNullOrEmpty(search))
        {
            command.CommandText = "SELECT COUNT(*) FROM Conversations";
        }
        else
        {
            command.CommandText =
            $"""
            SELECT COUNT(*) FROM Conversations
            WHERE lower(UserMessage) LIKE $q OR lower({ResponseColumn}) LIKE $q
            """;
            command.Parameters.AddWithValue("$q", $"%{search.ToLower()}%");
        }

        return (long)command.ExecuteScalar()!;
    }

    /// <summary>Страница истории: новые сверху (Id DESC), с учётом смещения.</summary>
    /// <param name="search">Подстрока поиска по вопросу и ответу (пусто — все).</param>
    public List<Conversation> GetPage(int limit, int offset, string search = "")
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        if (string.IsNullOrEmpty(search))
        {
            command.CommandText =
            $"""
            SELECT Id, UserMessage, {ResponseColumn}, Timestamp
            FROM Conversations
            ORDER BY Id DESC
            LIMIT $limit OFFSET $offset
            """;
        }
        else
        {
            command.CommandText =
            $"""
            SELECT Id, UserMessage, {ResponseColumn}, Timestamp
            FROM Conversations
            WHERE lower(UserMessage) LIKE $q OR lower({ResponseColumn}) LIKE $q
            ORDER BY Id DESC
            LIMIT $limit OFFSET $offset
            """;
            command.Parameters.AddWithValue("$q", $"%{search.ToLower()}%");
        }

        command.Parameters.AddWithValue("$limit", limit);
        command.Parameters.AddWithValue("$offset", offset);

        using var reader = command.ExecuteReader();

        var conversations = new List<Conversation>();

        while (reader.Read())
        {
            conversations.Add(new Conversation
            {
                Id = reader.GetInt64(0),
                UserMessage = reader.GetString(1),
                ZereResponse = reader.GetString(2),
                Timestamp = DateTime.Parse(reader.GetString(3), System.Globalization.CultureInfo.InvariantCulture)
            });
        }

        return conversations;
    }
}
