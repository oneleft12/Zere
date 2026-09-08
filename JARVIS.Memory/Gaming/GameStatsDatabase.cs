using Microsoft.Data.Sqlite;

namespace JARVIS.Memory.Gaming;

public class GameStatsDatabase
{
    private const string DatabaseName = "jarvis_games.db";

    public SqliteConnection CreateConnection()
    {
        var connection = new SqliteConnection($"Data Source={DatabaseName}");

        connection.Open();

        CreateTables(connection);

        return connection;
    }

    private void CreateTables(SqliteConnection connection)
    {
        var command = connection.CreateCommand();

        command.CommandText =
        """
        CREATE TABLE IF NOT EXISTS GameStats(
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            Game TEXT NOT NULL,
            Date TEXT NOT NULL,
            Minutes INTEGER NOT NULL
        );
        """;

        command.ExecuteNonQuery();
    }
}