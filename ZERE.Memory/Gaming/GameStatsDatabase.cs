using Microsoft.Data.Sqlite;

namespace ZERE.Memory.Gaming;

public class GameStatsDatabase
{
    private readonly string _databasePath;

    public GameStatsDatabase()
    {
        var folder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ZERE");

        Directory.CreateDirectory(folder);

        _databasePath = Path.Combine(folder, "zere_games.db");
    }

    public SqliteConnection CreateConnection()
    {
        var connection = new SqliteConnection($"Data Source={_databasePath}");

        connection.Open();

        CreateTables(connection);

        return connection;
    }

    private void CreateTables(SqliteConnection connection)
    {
        using var command = connection.CreateCommand();

        command.CommandText =
        """
        CREATE TABLE IF NOT EXISTS GameStats(
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            Game TEXT NOT NULL,
            Date TEXT NOT NULL,
            Minutes INTEGER NOT NULL,
            UNIQUE(Game, Date)
        );
        """;

        command.ExecuteNonQuery();
    }
}