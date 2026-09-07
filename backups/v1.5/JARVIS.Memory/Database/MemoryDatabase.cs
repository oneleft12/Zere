using Microsoft.Data.Sqlite;

namespace JARVIS.Memory.Database;

public class MemoryDatabase
{
    private readonly string _databasePath;

    public MemoryDatabase()
    {
        var folder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "JARVIS");

        Directory.CreateDirectory(folder);

        _databasePath = Path.Combine(folder, "jarvis.db");

        Initialize();
    }

    public SqliteConnection CreateConnection()
    {
        return new SqliteConnection($"Data Source={_databasePath}");
    }

    private void Initialize()
    {
        using var connection = CreateConnection();

        connection.Open();

        var command = connection.CreateCommand();

        command.CommandText =
        """
        CREATE TABLE IF NOT EXISTS Conversations
        (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            UserMessage TEXT NOT NULL,
            JarvisResponse TEXT NOT NULL,
            Timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS Meta
        (
            Key TEXT PRIMARY KEY,
            Value TEXT NOT NULL
        );
        """;

        command.ExecuteNonQuery();
    }
}