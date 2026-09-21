using JARVIS.Core;
using JARVIS.Core.Configuration;
using JARVIS.Core.Dependencies;
using JARVIS.Core.Logging;
using JARVIS.Core.Plugins;
using JARVIS.Core.Plugins.Settings;
using JARVIS.Memory.Database;
using JARVIS.Voice;
using JARVIS.Voice.WakeWord;
using Microsoft.Extensions.DependencyInjection;

var config = JarvisConfig.Load();
var logger = new LogService();

logger.Info($"{config.AssistantName} OS {config.Version} запускается.");

Console.WriteLine($"""
=================================
        {config.AssistantName}
=================================

Версия: {config.Version}
Модель: {config.Model}
Язык: {config.Language}

""");

var checker = new DependencyChecker(config);
var results = checker.RunAll();
checker.PrintReport();

if (!checker.AllCriticalPassed())
{
    checker.OfferInstall();
}

if (!checker.AllCriticalPassed())
{
    Console.WriteLine("Критические зависимости не выполнены.");
    Console.WriteLine("Устраните ошибки выше и запустите снова.");
    Console.WriteLine("Нажмите Enter для выхода...");
    Console.ReadLine();
    return;
}

Console.WriteLine("Все зависимости в порядке.\n");

// Предложить установку голосовых компонентов (не критичные)
if (config.VoiceEnabled)
{
    checker.OfferVoiceInstall();
}

var services = ServiceRegistration.Create();

_ = services.GetRequiredService<MemoryDatabase>();

var jarvis = services.GetRequiredService<JarvisEngine>();
var voiceManager = new VoiceManager();

var activePersonality = jarvis.PluginManager.ActivePersonality;
if (activePersonality != null)
{
    Console.WriteLine($"[Личность] {activePersonality.Name} | Стиль: {activePersonality.Style}\n");
}

if (config.VoiceEnabled)
{
    voiceManager.Initialize(activePersonality?.Style.ToString());
    Console.WriteLine("[Голос] Режим: текст + голос");
}
else
{
    Console.WriteLine("[Голос] Отключен. Только текстовый режим.");
}

Console.WriteLine("Команды: 'настройки' — панель настроек, 'exit' — выход");
Console.WriteLine("         'голос' / 'voice' — переключить голосовой режим\n");

var voiceMode = false;

while (true)
{
    if (voiceMode)
    {
        // Режим с ключевым словом
        if (voiceManager.Config.WakeWordEnabled)
        {
            var wakeDetector = voiceManager.EnableWakeWord();

            Console.WriteLine("\n💤 Спящий режим. Скажите 'Джарвис' для активации.");
            Console.WriteLine("   Скажите 'выход' для отключения голосового режима.\n");

            using var cts = new CancellationTokenSource();

            // Обработка Ctrl+C для выхода из sleep mode
            ConsoleCancelEventHandler cancelHandler = (_, e) =>
            {
                e.Cancel = true;
                cts.Cancel();
            };
            Console.CancelKeyPress += cancelHandler;

            try
            {
                while (voiceMode)
                {
                    Console.Write("💤 ");
                    Console.Out.Flush();

                    // Ожидаем ключевое слово
                    var wakeDetected = await voiceManager.WaitForWakeWordAsync(cts.Token);

                    if (!wakeDetected)
                    {
                        // Отмена или выход
                        if (cts.IsCancellationRequested)
                        {
                            voiceMode = false;
                            Console.WriteLine("\n[Голос] Текстовый режим.\n");
                            break;
                        }
                        continue;
                    }

                    // Ключевое слово обнаружено!
                    Console.WriteLine("🎧 Слушаю вашу команду...\n");

                    // Слушаем команду
                    var voiceInput = await voiceManager.ListenCommandAsync();

                    if (string.IsNullOrWhiteSpace(voiceInput))
                    {
                        Console.WriteLine("⚠️ Не удалось распознать команду.\n");
                        Console.WriteLine("💤 Возвращаюсь в спящий режим.\n");
                        continue;
                    }

                    Console.WriteLine($"Вы (голос): {voiceInput}\n");

                    if (voiceInput.ToLower() == "выход" || voiceInput.ToLower() == "стоп")
                    {
                        voiceMode = false;
                        Console.WriteLine("[Голос] Текстовый режим.\n");
                        break;
                    }

                    try
                    {
                        var answer = await jarvis.ProcessAsync(voiceInput);

                        logger.Info($"JARVIS: {answer}");

                        Console.WriteLine($"\nJARVIS: {answer}\n");

                        if (config.VoiceEnabled)
                        {
                            await voiceManager.SpeakAsync(answer);
                        }
                    }
                    catch (Exception ex)
                    {
                        logger.Error(ex.Message);
                        Console.WriteLine($"\nОшибка: {ex.Message}\n");
                    }

                    Console.WriteLine("💤 Возвращаюсь в спящий режим.\n");
                }
            }
            catch (OperationCanceledException)
            {
                voiceMode = false;
                Console.WriteLine("\n[Голос] Текстовый режим.\n");
            }
            finally
            {
                Console.CancelKeyPress -= cancelHandler;
            }
        }
        else
        {
            // Обычный режим без ключевого слова (старый вариант)
            Console.Write("[ГОЛОС] Скажите команду... ");

            var voiceInput = await voiceManager.ListenAsync();

            if (string.IsNullOrWhiteSpace(voiceInput))
            {
                Console.WriteLine("Не удалось распознать речь.\n");
                continue;
            }

            Console.WriteLine($"Вы (голос): {voiceInput}\n");

            if (voiceInput.ToLower() == "выход" || voiceInput.ToLower() == "стоп")
            {
                voiceMode = false;
                Console.WriteLine("[Голос] Текстовый режим.\n");
                continue;
            }

            try
            {
                var answer = await jarvis.ProcessAsync(voiceInput);

                logger.Info($"JARVIS: {answer}");

                Console.WriteLine($"\nJARVIS: {answer}\n");

                if (config.VoiceEnabled)
                {
                    await voiceManager.SpeakAsync(answer);
                }
            }
            catch (Exception ex)
            {
                logger.Error(ex.Message);
                Console.WriteLine($"\nОшибка: {ex.Message}\n");
            }
        }
    }
    else
    {
        Console.Write("Вы: ");

        var message = Console.ReadLine();

        if (string.IsNullOrWhiteSpace(message))
            continue;

        if (message.ToLower() == "exit")
            break;

        if (message.ToLower() == "настройки" || message.ToLower() == "settings")
        {
            var pluginManager = services.GetRequiredService<PluginManager>();
            var pluginConfig = services.GetRequiredService<PluginConfig>();

            var settingsMenu = new SettingsMenu(pluginManager, pluginConfig);
            settingsMenu.Show();

            activePersonality = jarvis.PluginManager.ActivePersonality;
            if (activePersonality != null)
            {
                Console.WriteLine($"\n[Личность] {activePersonality.Name} | Стиль: {activePersonality.Style}\n");

                if (config.VoiceEnabled)
                {
                    voiceManager.SetPersonalityVoice(activePersonality.Style.ToString());
                }
            }
            continue;
        }

        if (message.ToLower() == "голос" || message.ToLower() == "voice")
        {
            if (!config.VoiceEnabled)
            {
                Console.WriteLine("\nГолос отключен в конфиге.\n");
                continue;
            }

            voiceMode = true;
            Console.WriteLine("\n[Голос] Голосовой режим активирован. Скажите 'выход' для отключения.\n");
            continue;
        }

        try
        {
            var answer = await jarvis.ProcessAsync(message);

            logger.Info($"JARVIS: {answer}");

            Console.WriteLine();
            Console.WriteLine($"JARVIS: {answer}");
            Console.WriteLine();

            if (config.VoiceEnabled)
            {
                await voiceManager.SpeakAsync(answer);
            }
        }
        catch (Exception ex)
        {
            logger.Error(ex.Message);

            Console.WriteLine();
            Console.WriteLine($"Ошибка: {ex.Message}");
            Console.WriteLine();
        }
    }
}

voiceManager.Dispose();
logger.Info("JARVIS завершил работу.");
