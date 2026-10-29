using ZERE.AI;
using ZERE.App.Api;
using ZERE.Core;
using ZERE.Core.Configuration;
using ZERE.Core.Context;
using ZERE.Core.Dependencies;
using ZERE.Core.Logging;
using ZERE.Core.Plugins;
using ZERE.Core.Plugins.Settings;
using ZERE.Memory.Database;
using ZERE.Tools.Applications;
using ZERE.Tools.Windows;
using ZERE.Tools.Windows.Processes;
using ZERE.Voice;
using ZERE.Voice.WakeWord;
using Microsoft.Extensions.DependencyInjection;

var config = ZereConfig.Load();
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
// зависимостей и голоса (запускает CI: dotnet run --project ZERE.App -- --panel).
if (args.Contains("--panel"))
{
    // Порт панели для контрактных тестов и отладки: `--panel --port 8091`
    // (или `--panel --port=8091`). По умолчанию — 8080, как в проде.
    var panelPort = PanelServer.DefaultPort;
    var portIndex = Array.IndexOf(args, "--port");
    var portValue = portIndex >= 0 && portIndex + 1 < args.Length
        ? args[portIndex + 1]
        : args.FirstOrDefault(a => a.StartsWith("--port=", StringComparison.Ordinal))?["--port=".Length..];

    if (int.TryParse(portValue, out var parsedPort) && parsedPort is > 0 and <= 65535)
        panelPort = parsedPort;

    var panelServices = ServiceRegistration.Create(config);
    _ = panelServices.GetRequiredService<MemoryDatabase>();

    var panelEngine = panelServices.GetRequiredService<ZereEngine>();
    var panelMemory = panelServices.GetRequiredService<MemoryRepository>();

    // Ленивые сервисы (Whisper/Silero/Pocket): конструктор только строит пути,
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
        panelVoice,
        panelServices.GetRequiredService<RuntimeContext>(),
        panelServices.GetRequiredService<AiService>(),
        port: panelPort);
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

// Облачный ключ (config/ai.json или окружение владельца) делает Ollama
// необязательной: ZERE стартует и отвечает через облачную модель.
var checker = new DependencyChecker(config, AiSettings.Load().HasKey());
var results = checker.RunAll();
checker.PrintReport();

if (!checker.AllCriticalPassed())
{
    checker.OfferInstall();
}

if (!checker.AllCriticalPassed())
{
    Console.WriteLine("Критические зависимости не выполнены.");

    if (AiSettings.Load().HasKey())
        Console.WriteLine("Настроен облачный API-ключ — он используется приоритетно.");

    Console.WriteLine("Откройте панель → «Подключение ИИ»: введите API-ключ или установите локальную модель.");
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

var zere = services.GetRequiredService<ZereEngine>();
var voiceManager = new VoiceManager();

// Локальная панель (этап 1 GUI-плана): loopback + токен, контракт
// docs/api/openapi.yaml. Сбой порта не должен ронять консоль.
var panel = new PanelServer(
    config,
    zere,
    services.GetRequiredService<MemoryRepository>(),
    services.GetRequiredService<ConversationRepository>(),
    services.GetRequiredService<PluginConfig>(),
    services.GetRequiredService<ProcessService>(),
    services.GetRequiredService<SafeActionManager>(),
    services.GetRequiredService<ApplicationLauncher>(),
    voiceManager,
    services.GetRequiredService<RuntimeContext>(),
    services.GetRequiredService<AiService>());

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

var activePersonality = zere.PluginManager.ActivePersonality;
if (activePersonality != null)
{
    Console.WriteLine($"[Личность] {activePersonality.Name} | Стиль: {activePersonality.Style}\n");
}

// Настройки голоса и доступность TTS применяем всегда, в том числе при
// выключенном голосовом выводе: панель умеет тестировать синтез («Озвучить»
// на экране «Голос»), а Initialize() только проверяет инструментарий — модель
// грузится при первом синтезе. Иначе панель отвечала 503 «Синтез речи
// недоступен: Silero доступен (ленивая загрузка модели при первом синтезе)».
// Паритет с Python: main.py → zere/voice/voice_bootstrap.py.

// Громкость голосового вывода из config.json (voiceVolume).
voiceManager.Config.Volume = (float)config.VoiceVolume;

// DSP-обработка озвучки из config.json (audioProcessing, дефолт true).
// Переключается на лету из панели — читается на каждое предложение.
voiceManager.Config.AudioProcessing = config.AudioProcessing;

voiceManager.ConfigureTts(config.TtsEngine, config.VoiceReferencePath);
voiceManager.ConfigureStt(config.SttEngine);

// Слово-триггер из config.json (wake*): движок (auto | kws | whisper),
// путь к ONNX-модели, порог/сглаживание/cooldown и отсечка тишины.
// Пустые значения = значения из манифеста модели (docs/WAKE_WORD.md).
voiceManager.Config.WakeEngine = config.WakeEngine;
voiceManager.Config.WakeModelPath = config.WakeModelPath;
voiceManager.Config.WakeThreshold = config.WakeThreshold;
voiceManager.Config.WakeMinConsecutive = config.WakeMinConsecutive;
voiceManager.Config.WakeCooldownMs = config.WakeCooldownMs;
voiceManager.Config.WakeEnergyGate = config.WakeEnergyGate;

voiceManager.Initialize(activePersonality?.Style.ToString());

if (config.VoiceEnabled)
{
    Console.WriteLine("[Голос] Режим: текст + голос");

    // Этап 1 (анализ S3): предзагрузка STT в фоне — первая транскрибация
    // не должна ждать загрузку модели; для GigaAM здесь же скачивается
    // модель (~163 МБ), если её ещё нет. Это признак включённого голоса:
    // выключенный голосовой ввод не должен качать модель.
    _ = Task.Run(() => voiceManager.PreloadStt());
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
        var ai = services.GetRequiredService<AiService>().Proxy;
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
            voiceManager.EnableWakeWord();

            var wakeWord = voiceManager.Config.WakeWord ?? "зере";

            Console.WriteLine($"\n💤 Спящий режим. Скажите '{wakeWord}' для активации.");
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
                    Console.Write($"💬 Напишите 'выход' или скажите '{wakeWord}': ");
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
                        var answer = await zere.ProcessAsync(voiceInput);

                        logger.Info($"ZERE: {answer}");

                        Console.WriteLine($"\nZERE: {answer}\n");

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
                var answer = await zere.ProcessAsync(voiceInput);

                logger.Info($"ZERE: {answer}");

                Console.WriteLine($"\nZERE: {answer}\n");

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

            activePersonality = zere.PluginManager.ActivePersonality;
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
                Console.WriteLine("Перезапустите ZERE — при старте сервер TTS закодирует референс в голос.\n");
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
            var answer = await zere.ProcessAsync(message);

            logger.Info($"ZERE: {answer}");

            Console.WriteLine();
            Console.WriteLine($"ZERE: {answer}");
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
logger.Info("ZERE завершил работу.");
