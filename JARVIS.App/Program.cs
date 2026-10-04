using JARVIS.AI;
using JARVIS.App.Api;
using JARVIS.Core;
using JARVIS.Core.Configuration;
using JARVIS.Core.Context;
using JARVIS.Core.Dependencies;
using JARVIS.Core.Logging;
using JARVIS.Core.Plugins;
using JARVIS.Core.Plugins.Settings;
using JARVIS.Memory.Database;
using JARVIS.Tools.Applications;
using JARVIS.Tools.Windows;
using JARVIS.Tools.Windows.Processes;
using JARVIS.Voice;
using JARVIS.Voice.WakeWord;
using Microsoft.Extensions.DependencyInjection;

var config = JarvisConfig.Load();
var logger = new LogService();

logger.Info($"{config.AssistantName} OS {config.Version} запускается.");

// Открывает панель в браузере (этап 5 GUI-плана): сбой браузера
// не должен ронять консоль. Это фолбэк — окно приложения (этап 6)
// само уходит сюда, если WebView2 Runtime недоступен.
static void OpenPanelInBrowser(string url, LogService logger)
{
    try
    {
        System.Diagnostics.Process.Start(
            new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true });
        Console.WriteLine($"[Панель] Открыта в браузере: {url}");
    }
    catch (Exception ex)
    {
        logger.Error($"PanelBrowser: {ex.Message}");
        Console.WriteLine($"[Панель] Браузер не открылся — вручную: {url}");
    }
}

// Режим контрактных тестов панели: только API-ядро, без проверки
// зависимостей и голоса (запускает CI: dotnet run --project JARVIS.App -- --panel).
if (args.Contains("--panel"))
{
    var panelServices = ServiceRegistration.Create(config);
    _ = panelServices.GetRequiredService<MemoryDatabase>();

    var panelEngine = panelServices.GetRequiredService<JarvisEngine>();
    var panelMemory = panelServices.GetRequiredService<MemoryRepository>();

    // Ленивые сервисы (Whisper/Piper/Pocket): конструктор только строит пути,
    // поэтому панель в режиме --panel получает голос без инициализации звука.
    var panelVoice = new VoiceManager();

    var testPanel = new PanelServer(
        config,
        panelEngine,
        panelMemory,
        panelServices.GetRequiredService<ConversationRepository>(),
        panelServices.GetRequiredService<PluginConfig>(),
        panelServices.GetRequiredService<ProcessService>(),
        panelServices.GetRequiredService<SafeActionManager>(),
        panelServices.GetRequiredService<ApplicationLauncher>(),
        panelVoice);
    testPanel.Start();

    Console.WriteLine($"[Панель] http://127.0.0.1:{testPanel.Port} (токен: config/panel.token)");

    var quit = new ManualResetEvent(false);

    Console.CancelKeyPress += (_, e) =>
    {
        e.Cancel = true;
        quit.Set();
    };

    quit.WaitOne();
    testPanel.Dispose();
    return;
}

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

var services = ServiceRegistration.Create(config);

_ = services.GetRequiredService<MemoryDatabase>();

var jarvis = services.GetRequiredService<JarvisEngine>();
var voiceManager = new VoiceManager();

// Локальная панель (этап 1 GUI-плана): loopback + токен, контракт
// docs/api/openapi.yaml. Сбой порта не должен ронять консоль.
var panel = new PanelServer(
    config,
    jarvis,
    services.GetRequiredService<MemoryRepository>(),
    services.GetRequiredService<ConversationRepository>(),
    services.GetRequiredService<PluginConfig>(),
    services.GetRequiredService<ProcessService>(),
    services.GetRequiredService<SafeActionManager>(),
    services.GetRequiredService<ApplicationLauncher>(),
    voiceManager);

// URL панели — для команды «панель»; null, если сервер не поднялся.
string? panelUrl = null;

try
{
    panel.Start();
    panelUrl = $"http://127.0.0.1:{panel.Port}";
    Console.WriteLine($"[Панель] {panelUrl} (токен: config/panel.token)");

    // Авто-открытие панели при старте (этапы 5–6): отдельное окно
    // приложения (WebView2), фолбэк — браузер.
    PanelWindowHost.Open(panelUrl, logger, url => OpenPanelInBrowser(url, logger));
}
catch (Exception ex)
{
    logger.Error($"PanelServer: {ex.Message}");
    Console.WriteLine("[Панель] Не удалось запустить локальный сервер (порт занят?).");
}

var activePersonality = jarvis.PluginManager.ActivePersonality;
if (activePersonality != null)
{
    Console.WriteLine($"[Личность] {activePersonality.Name} | Стиль: {activePersonality.Style}\n");
}

if (config.VoiceEnabled)
{
    // Громкость голосового вывода из config.json (voiceVolume).
    voiceManager.Config.Volume = (float)config.VoiceVolume;
    voiceManager.ConfigureTts(config.TtsEngine, config.VoiceReferencePath);
    voiceManager.Initialize(activePersonality?.Style.ToString());
    Console.WriteLine("[Голос] Режим: текст + голос");

    // Этап 1 (анализ S3): предзагрузка Whisper в фоне — первая транскрибация
    // не должна ждать загрузку модели ggml.
    _ = Task.Run(() => voiceManager.PreloadWhisper());
}
else
{
    Console.WriteLine("[Голос] Отключен. Только текстовый режим.");
}

// Этап 1 (анализ S5): прогрев Ollama в фоне — убирает загрузку модели
// с первого запроса; keep_alive из конфига удерживает её в памяти.
_ = Task.Run(async () =>
{
    try
    {
        var ai = services.GetRequiredService<OllamaClient>();
        await ai.WarmupAsync();
    }
    catch (Exception ex)
    {
        logger.Error($"Warmup: {ex.Message}");
    }
});

Console.WriteLine("Команды: 'настройки' — панель настроек, 'exit' — выход");
Console.WriteLine("         'панель' / 'panel' — открыть окно панели");
Console.WriteLine("         'голос' / 'voice' — переключить голосовой режим");
Console.WriteLine("         'записать голос' — записать референс для клонирования\n");

var voiceMode = false;
var runtime = services.GetRequiredService<RuntimeContext>();

while (true)
{
    // Голосовой режим этой реплики → AIHandler отвечает коротко (этап 1).
    runtime.VoiceMode = voiceMode;

    // Вышли из голосового режима → детектор и микрофон освобождаются,
    // при следующем входе создаётся заново (общий Whisper переиспользуется).
    if (!voiceMode)
        voiceManager.DisableWakeWord();

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

        if (message.ToLower() == "панель" || message.ToLower() == "panel")
        {
            if (panelUrl != null)
            {
                PanelWindowHost.Open(panelUrl, logger, url => OpenPanelInBrowser(url, logger));
            }
            else
            {
                Console.WriteLine("[Панель] Сервер не запущен — команда недоступна.");
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

panel.Dispose();
voiceManager.Dispose();
logger.Info("JARVIS завершил работу.");
