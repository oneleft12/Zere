using JARVIS.Memory.Models;

namespace JARVIS.Memory.Database;

public class ConversationRepository
{
    private readonly MemoryDatabase _database;

    public ConversationRepository(MemoryDatabase database)
    {
        _database = database;
    }

    public void Save(string userMessage, string jarvisResponse)
    {
        using var connection = _database.CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        """
        INSERT INTO Conversations
        (UserMessage, JarvisResponse, Timestamp)
        VALUES ($user, $jarvis, $time)
        """;

        command.Parameters.AddWithValue("$user", userMessage);
        command.Parameters.AddWithValue("$jarvis", jarvisResponse);
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
        """
        SELECT Id, UserMessage, JarvisResponse, Timestamp
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
                JarvisResponse = reader.GetString(2),
                Timestamp = DateTime.Parse(reader.GetString(3), System.Globalization.CultureInfo.InvariantCulture)
            });
        }

        return conversations;
    }
}
