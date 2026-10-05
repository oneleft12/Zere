using Microsoft.Data.Sqlite;

namespace ZERE.Memory.Database;

public class MemoryDatabase : IDisposable
{
    private readonly string _databasePath;

    /// <summary>
    /// Колонка ответа ассистента в таблице Conversations. До ребрендинга
    /// называлась JarvisResponse — старую базу не мигрируем, а работаем с
    /// той схемой, которая уже есть (история прошлых версий не теряется).
    /// </summary>
    public string ResponseColumn { get; private set; } = "ZereResponse";

    public MemoryDatabase()
    {
        var folder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ZERE");

        Directory.CreateDirectory(folder);

        _databasePath = Path.Combine(folder, "zere.db");

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

        DetectResponseColumn(connection);

        var command = connection.CreateCommand();

        command.CommandText =
        """
        CREATE TABLE IF NOT EXISTS Conversations
        (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            UserMessage TEXT NOT NULL,
            ZereResponse TEXT NOT NULL,
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

    /// <summary>
    /// Определяет имя колонки ответа в существующей базе. PRAGMA table_info
    /// возвращает пустой набор, если таблицы ещё нет — тогда остаётся новое
    /// имя, и CREATE TABLE ниже создаёт схему с нуля.
    /// </summary>
    private void DetectResponseColumn(SqliteConnection connection)
    {
        var command = connection.CreateCommand();

        command.CommandText = "PRAGMA table_info(Conversations)";

        var columns = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        using (var reader = command.ExecuteReader())
        {
            while (reader.Read())
            {
                columns.Add(reader.GetString(1));
            }
        }

        if (columns.Contains("ZereResponse"))
        {
            ResponseColumn = "ZereResponse";
        }
        else if (columns.Contains("JarvisResponse"))
        {
            ResponseColumn = "JarvisResponse";
        }
    }

    public void Dispose()
    {
        // IDisposable implemented for interface consistency; no unmanaged resources to release.
        // Connections are opened/closed per operation via CreateConnection().
    }
}
