using Microsoft.Data.Sqlite;

namespace JARVIS.Memory.Database;

public class MemoryDatabase : IDisposable
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

        CREATE TABLE IF NOT EXISTS Memories
        (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            Key TEXT NOT NULL UNIQUE,
            Value TEXT NOT NULL,
            Category TEXT NOT NULL DEFAULT 'User',
            CreatedAt TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS Meta
        (
            Key TEXT PRIMARY KEY,
            Value TEXT NOT NULL
        );
        """;

        command.ExecuteNonQuery();
    }

    public void Dispose()
    {
        // IDisposable implemented for interface consistency; no unmanaged resources to release.
        // Connections are opened/closed per operation via CreateConnection().
    }
}
