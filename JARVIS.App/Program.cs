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
    voiceManager.ConfigureTts(config.TtsEngine, config.VoiceReferencePath);
    voiceManager.Initialize(activePersonality?.Style.ToString());
    Console.WriteLine("[Голос] Режим: текст + голос");
}
else
{
    Console.WriteLine("[Голос] Отключен. Только текстовый режим.");
}

Console.WriteLine("Команды: 'настройки' — панель настроек, 'exit' — выход");
Console.WriteLine("         'голос' / 'voice' — переключить голосовой режим");
Console.WriteLine("         'записать голос' — записать референс для клонирования\n");

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
            Console.WriteLine("   Или напишите 'выход' для отключения голосового режима.\n");

            using var cts = new CancellationTokenSource();

            // Обработка Ctrl+C
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
                    Console.Write("💬 Напишите 'выход' или скажите 'Джарвис': ");
                    Console.Out.Flush();

                    // Параллельно: слушаем микрофон И ждём ввод текста
                    var wakeTask = voiceManager.WaitForWakeWordAsync(cts.Token);

                    // Ждём либо wake word, либо текстовый ввод
                    while (!wakeTask.IsCompleted && !cts.IsCancellationRequested)
                    {
                        // Проверяем, есть ли текст в консоли (без блокировки)
                        if (Console.KeyAvailable)
                        {
                            var textInput = Console.ReadLine()?.Trim().ToLower();
                            if (textInput == "выход" || textInput == "стоп" || textInput == "exit")
                            {
                                cts.Cancel();
                                break;
                            }
                        }

                        await Task.Delay(100);
                    }

                    // Ждём завершения задачи wake word
                    var wakeDetected = false;
                    try
                    {
                        wakeDetected = await wakeTask;
                    }
                    catch (OperationCanceledException) { }

                    if (cts.IsCancellationRequested)
                    {
                        voiceMode = false;
                        Console.WriteLine("\n[Голос] Текстовый режим.\n");
                        break;
                    }

                    if (!wakeDetected)
                        continue;

                    // Ключевое слово обнаружено!
                    Console.WriteLine("\n🎧 Слушаю вашу команду...");
                    Console.WriteLine("   (или напишите 'выход')\n");

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

        if (message.ToLower() == "записать голос" || message.ToLower() == "record voice")
        {
            if (!config.VoiceEnabled)
            {
                Console.WriteLine("\nГолос отключен в конфиге.\n");
                continue;
            }

            Console.WriteLine("\n📖 Читайте вслух текст в обычном темпе, без шума вокруг.");
            var referencePath = await voiceManager.RecordVoiceReferenceAsync(15);

            if (referencePath != null)
            {
                config.VoiceReferencePath = referencePath;
                config.Save();
                Console.WriteLine($"\n✅ Голос сохранён: {referencePath}");
                Console.WriteLine("Перезапустите JARVIS — при старте сервер TTS закодирует референс в голос.\n");
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
