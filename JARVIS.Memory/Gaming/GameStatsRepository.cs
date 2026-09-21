using Microsoft.Data.Sqlite;

namespace JARVIS.Memory.Gaming;

public class GameStatsRepository
{
    private readonly GameStatsDatabase _db = new();

    public void AddMinute(string game)
    {
        using var connection = _db.CreateConnection();

        var today = DateTime.Today.ToString("yyyy-MM-dd");

        using var command = connection.CreateCommand();
        command.CommandText =
        """
        INSERT INTO GameStats(Game, Date, Minutes)
        VALUES($game, $date, 1)
        ON CONFLICT(Game, Date)
        DO UPDATE SET Minutes = Minutes + 1
        """;

        command.Parameters.AddWithValue("$game", game);
        command.Parameters.AddWithValue("$date", today);

        command.ExecuteNonQuery();
    }

    public List<GameStat> GetToday()
    {
        using var connection = _db.CreateConnection();

        using var command = connection.CreateCommand();

        command.CommandText =
        """
        SELECT Id, Game, Date, Minutes
        FROM GameStats
        WHERE Date=$date
        ORDER BY Minutes DESC
        """;

        command.Parameters.AddWithValue(
            "$date",
            DateTime.Today.ToString("yyyy-MM-dd"));

        using var reader = command.ExecuteReader();

        var list = new List<GameStat>();

        while (reader.Read())
        {
            list.Add(new GameStat
            {
                Id = reader.GetInt64(0),
                Game = reader.GetString(1),
                Date = DateTime.Parse(reader.GetString(2)),
                Minutes = reader.GetInt32(3)
            });
        }

        return list;
    }

    public void Clear()
    {
        using var connection = _db.CreateConnection();

        using var command = connection.CreateCommand();

        command.CommandText = "DELETE FROM GameStats";

        command.ExecuteNonQuery();
    }
}
