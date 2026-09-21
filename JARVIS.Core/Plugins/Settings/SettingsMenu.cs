using JARVIS.Core.Plugins.Interfaces;

namespace JARVIS.Core.Plugins.Settings;

public class SettingsMenu
{
    private readonly PluginManager _pluginManager;
    private readonly PluginConfig _config;

    public SettingsMenu(PluginManager pluginManager, PluginConfig config)
    {
        _pluginManager = pluginManager;
        _config = config;
    }

    public void Show()
    {
        while (true)
        {
            Console.Clear();
            Console.WriteLine("╔══════════════════════════════════════╗");
            Console.WriteLine("║       НАСТРОЙКИ JARVIS v1.7        ║");
            Console.WriteLine("╠══════════════════════════════════════╣");
            Console.WriteLine("║  1. Личность ассистента            ║");
            Console.WriteLine("║  2. Плагины                        ║");
            Console.WriteLine("║  3. Конфигурация                   ║");
            Console.WriteLine("║  4. О плагинах                     ║");
            Console.WriteLine("║  0. Выход                          ║");
            Console.WriteLine("╚══════════════════════════════════════╝");
            Console.Write("\nВыберите пункт: ");

            var choice = Console.ReadLine()?.Trim();

            switch (choice)
            {
                case "1":
                    ShowPersonalityMenu();
                    break;
                case "2":
                    ShowPluginsMenu();
                    break;
                case "3":
                    ShowConfigMenu();
                    break;
                case "4":
                    ShowAboutPlugins();
                    break;
                case "0":
                    return;
            }
        }
    }

    private void ShowPersonalityMenu()
    {
        var personality = _pluginManager.ActivePersonality;

        while (true)
        {
            Console.Clear();
            Console.WriteLine("╔══════════════════════════════════════╗");
            Console.WriteLine("║     ЛИЧНОСТЬ АССИСТЕНТА            ║");
            Console.WriteLine("╠══════════════════════════════════════╣");
            Console.WriteLine($"║  Текущий стиль: {(personality?.Style.ToString() ?? "Не задан")}");
            Console.WriteLine("╠══════════════════════════════════════╣");

            var personalities = _pluginManager.Personalities;
            var index = 1;

            foreach (var p in personalities)
            {
                foreach (var style in p.GetAvailableStyles())
                {
                    var isActive = personality?.Style.ToString() == style ? " [АКТИВЕН]" : "";
                    Console.WriteLine($"║  {index}. {style}{isActive}");
                    index++;
                }
            }

            Console.WriteLine("╠══════════════════════════════════════╣");
            Console.WriteLine("║  0. Назад                          ║");
            Console.WriteLine("╚══════════════════════════════════════╝");
            Console.Write("\nВыберите стиль: ");

            var choice = Console.ReadLine()?.Trim();

            if (choice == "0")
                return;

            if (int.TryParse(choice, out var num) && num > 0 && num <= index - 1)
            {
                var allStyles = personalities.SelectMany(p => p.GetAvailableStyles()).ToList();
                var selectedStyle = allStyles[num - 1];

                foreach (var p in personalities)
                {
                    var availableStyles = p.GetAvailableStyles();

                    if (availableStyles.Contains(selectedStyle))
                    {
                        p.SetStyle(selectedStyle);
                        _pluginManager.SetActivePersonality(p.Id);
                        _config.ActivePersonalityId = p.Id;
                    }
                }
                PluginConfig.Save(_config);

                Console.WriteLine($"\nСтиль изменён на: {selectedStyle}");
                Console.WriteLine("Нажмите Enter для продолжения...");
                Console.ReadLine();
            }
        }
    }

    private void ShowPluginsMenu()
    {
        while (true)
        {
            Console.Clear();
            Console.WriteLine("╔══════════════════════════════════════╗");
            Console.WriteLine("║           ПЛАГИНЫ                  ║");
            Console.WriteLine("╠══════════════════════════════════════╣");

            var plugins = _pluginManager.Plugins;
            var index = 1;

            foreach (var plugin in plugins)
            {
                Console.WriteLine($"║  {index}. {plugin.Name} v{plugin.Version}");
                Console.WriteLine($"║     Тип: {plugin.Type} | Автор: {plugin.Author}");
                index++;
            }

            if (plugins.Count == 0)
                Console.WriteLine("║  Плагины не загружены               ║");

            Console.WriteLine("╠══════════════════════════════════════╣");
            Console.WriteLine("║  R. Перезагрузить плагины          ║");
            Console.WriteLine("║  0. Назад                          ║");
            Console.WriteLine("╚══════════════════════════════════════╝");
            Console.Write("\nВыберите действие: ");

            var choice = Console.ReadLine()?.Trim();

            if (choice == "0")
                return;

            if (choice?.ToLower() == "r")
            {
                _pluginManager.DisposeAll();
                _pluginManager.LoadAll();
                Console.WriteLine("Плагины перезагружены. Нажмите Enter...");
                Console.ReadLine();
            }
        }
    }

    private void ShowConfigMenu()
    {
        while (true)
        {
            Console.Clear();
            Console.WriteLine("╔══════════════════════════════════════╗");
            Console.WriteLine("║        КОНФИГУРАЦИЯ                ║");
            Console.WriteLine("╠══════════════════════════════════════╣");
            Console.WriteLine($"║  Активная личность: {_config.ActivePersonalityId}");
            Console.WriteLine($"║  Настроек плагинов: {_config.PluginSettings.Count}");
            Console.WriteLine("╠══════════════════════════════════════╣");
            Console.WriteLine("║  0. Назад                          ║");
            Console.WriteLine("╚══════════════════════════════════════╝");
            Console.Write("\nНажмите Enter для возврата...");
            Console.ReadLine();
            return;
        }
    }

    private void ShowAboutPlugins()
    {
        Console.Clear();
        Console.WriteLine("╔══════════════════════════════════════╗");
        Console.WriteLine("║       О ПЛАГИНАХ                   ║");
        Console.WriteLine("╠══════════════════════════════════════╣");
        Console.WriteLine("║  Плагины загружаются из папки      ║");
        Console.WriteLine("║  ./plugins/                        ║");
        Console.WriteLine("║                                    ║");
        Console.WriteLine("║  Формат: .dll файлы               ║");
        Console.WriteLine("║  Интерфейсы:                       ║");
        Console.WriteLine("║  - IPersonalityPlugin              ║");
        Console.WriteLine("║  - ICommandHandlerPlugin           ║");
        Console.WriteLine("║                                    ║");
        Console.WriteLine("║  Настройки применяются к началу   ║");
        Console.WriteLine("║  сессии. Внутри сессии нельзя     ║");
        Console.WriteLine("║  менять стиль.                     ║");
        Console.WriteLine("╚══════════════════════════════════════╝");
        Console.Write("\nНажмите Enter для возврата...");
        Console.ReadLine();
    }
}
