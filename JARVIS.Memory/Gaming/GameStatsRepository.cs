using Microsoft.Data.Sqlite;

namespace JARVIS.Memory.Gaming;

public class GameStatsRepository
{
    private readonly GameStatsDatabase _db = new();

    public void AddMinute(string game)
    {
        using var connection = _db.CreateConnection();

        var today = DateTime.Today.ToString("yyyy-MM-dd");

        var check = connection.CreateCommand();
        check.CommandText =
        """
        SELECT Minutes
        FROM GameStats
        WHERE Game=$game AND Date=$date
        """;

        check.Parameters.AddWithValue("$game", game);
        check.Parameters.AddWithValue("$date", today);

        var result = check.ExecuteScalar();

        if (result == null)
        {
            var insert = connection.CreateCommand();

            insert.CommandText =
            """
            INSERT INTO GameStats(Game, Date, Minutes)
            VALUES($game,$date,1)
            """;

            insert.Parameters.AddWithValue("$game", game);
            insert.Parameters.AddWithValue("$date", today);

            insert.ExecuteNonQuery();
        }
        else
        {
            var update = connection.CreateCommand();

            update.CommandText =
            """
            UPDATE GameStats
            SET Minutes=Minutes+1
            WHERE Game=$game AND Date=$date
            """;

            update.Parameters.AddWithValue("$game", game);
            update.Parameters.AddWithValue("$date", today);

            update.ExecuteNonQuery();
        }
    }

    public List<GameStat> GetToday()
    {
        using var connection = _db.CreateConnection();

        var command = connection.CreateCommand();

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

        var reader = command.ExecuteReader();

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

        var command = connection.CreateCommand();

        command.CommandText = "DELETE FROM GameStats";

        command.ExecuteNonQuery();
    }
}