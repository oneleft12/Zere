// ZERE — лаунчер приложения (zere.exe).
//
// Зачем он нужен: ассистент живёт на Python, и запуск «pythonw main.py
// --desktop» с ярлыка не даёт ничего, кроме невидимого процесса: нет ни
// иконки в панели задач, ни понятной ошибки, если окружение сломано. Этот
// файл — тонкая оболочка-супервизор, которая:
//
//   * не показывает консоль (WinExe);
//   * находит .venv рядом с собой и запускает `main.py --desktop` через
//     pythonw.exe (GUI-подсистема, без чёрного окна);
//   * ведёт весь вывод приложения в logs\desktop.log (а не «в никуда»);
//   * держит единственный экземпляр: повторный запуск поднимает окно ZERE;
//   * если приложение не стартовало — показывает окно с концом журнала.
//
// Компилируется системным csc (.NET Framework 4.x есть в любой Windows
// 10/11), поэтому zere.exe не требует ни dotnet-рантайма, ни установки
// питон-пакетов. Сборка: scripts\build-zere-exe.ps1 (её зовёт установщик).
//
// Код намеренно на C# 5: csc из .NET Framework не понимает интерполяцию
// строк и null-условный оператор.

using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("ZERE")]
[assembly: System.Reflection.AssemblyDescription("ZERE — персональный AI-ассистент")]
[assembly: System.Reflection.AssemblyProduct("ZERE")]
[assembly: System.Reflection.AssemblyCompany("ZERE Project")]
[assembly: System.Reflection.AssemblyVersion("1.8.0.0")]
[assembly: System.Reflection.AssemblyFileVersion("1.8.0.0")]

namespace Zere.Launcher
{
    internal static class Program
    {
        private const string MutexName = @"Local\ZERE.Desktop.Launcher";
        private const string WindowTitle = "ZERE";
        private const int StartupProbeMs = 7000;
        private const int LogTailChars = 1600;

        // Коды возврата main.py --desktop (zere/desktop/desktop.py):
        // 2 — окно не открылось, 3 — панель занята. Диалог уже показан
        // Python-стороной, второй раз пугать пользователя не нужно.
        private const int ExitWindowUnavailable = 2;
        private const int ExitAlreadyRunning = 3;

        private const int SwRestore = 9;

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr FindWindow(string className, string windowName);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int command);

        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();

            string root = FindRoot();
            if (root == null)
            {
                ShowError(
                    "ZERE не запущен: рядом с zere.exe нет main.py.\n\n" +
                    "Положите zere.exe в папку ZERE (там, где лежит main.py) " +
                    "или запустите installer\\Install-Zere.bat.");
                return 1;
            }

            bool console = HasFlag(args, "--console") || HasFlag(args, "--cli");

            // Повторный запуск: показываем уже открытое окно, второй сервер
            // панели не поднимаем (порт 8080 был бы занят).
            bool created;
            using (var mutex = new Mutex(true, MutexName, out created))
            {
                if (!created)
                {
                    ActivateExistingWindow();
                    return 0;
                }

                try
                {
                    return Run(root, args, console);
                }
                finally
                {
                    mutex.ReleaseMutex();
                }
            }
        }

        private static int Run(string root, string[] args, bool console)
        {
            string python = FindPython(root, console);
            if (python == null)
            {
                ShowError(
                    "ZERE не запущен: не найдено окружение Python.\n\n" +
                    "Ожидался файл .venv\\Scripts\\pythonw.exe в папке:\n" + root + "\n\n" +
                    "Запустите installer\\Install-Zere.bat — он создаст окружение " +
                    "и установит зависимости.");
                return 1;
            }

            string logPath = Path.Combine(root, "logs", "desktop.log");
            string arguments = BuildArguments(args, console);

            var startInfo = new ProcessStartInfo
            {
                FileName = python,
                Arguments = arguments,
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = !console,
                // Вывод НЕ перехватываем: у pythonw stdout/stderr — None, и
                // ZERE сам уводит их в logs\\desktop.log (zere/desktop/stdio.py).
                // Перехват в трубы оставлял бы их открытыми у дочерних
                // процессов WebView2, и WaitForExit() ждал бы вечно: окно
                // закрыто, а zere.exe висит без диалога.
            };

            var log = new LogWriter(logPath);
            log.Write("=== ZERE: " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " ===");
            log.Write("Запуск: " + python + " " + arguments);

            Process process;
            try
            {
                process = Process.Start(startInfo);
            }
            catch (Exception ex)
            {
                ShowError("ZERE не запущен: " + ex.Message);
                return 1;
            }

            if (process == null)
            {
                ShowError("ZERE не запущен: процесс Python не создан.");
                return 1;
            }

            // Даём приложению время открыть окно: если оно упало сразу,
            // пользователь должен увидеть причину, а не «мигнувший» exe.
            if (process.WaitForExit(StartupProbeMs))
            {
                process.WaitForExit();
                return Finish(process.ExitCode, logPath, console);
            }

            process.WaitForExit();

            log.Flush();

            return Finish(process.ExitCode, logPath, console);
        }

        private static int Finish(int exitCode, string logPath, bool console)
        {
            if (console)
            {
                return exitCode;
            }

            // 0 — пользователь закрыл окно; 2/3 — Python уже показал диалог.
            if (exitCode == 0 || exitCode == ExitWindowUnavailable || exitCode == ExitAlreadyRunning)
            {
                return exitCode;
            }

            ShowError(
                "ZERE завершился с ошибкой (код " + exitCode + ").\n\n" +
                "Последние строки журнала:\n" + Tail(logPath) + "\n\n" +
                "Полный журнал: " + logPath);
            return exitCode;
        }

        private static string BuildArguments(string[] args, bool console)
        {
            var builder = new StringBuilder("main.py");

            if (!console)
            {
                builder.Append(" --desktop");
            }

            foreach (string argument in args)
            {
                if (argument == "--console" || argument == "--cli")
                {
                    continue;
                }

                builder.Append(' ').Append(Quote(argument));
            }

            return builder.ToString();
        }

        private static string Quote(string argument)
        {
            if (argument.Length > 0 && argument.IndexOf(' ') < 0 && argument.IndexOf('"') < 0)
            {
                return argument;
            }

            return "\"" + argument.Replace("\"", "\\\"") + "\"";
        }

        private static string FindRoot()
        {
            string directory = AppDomain.CurrentDomain.BaseDirectory;
            DirectoryInfo current = new DirectoryInfo(directory);

            // zere.exe ожидается в корне ZERE, но допускаем запуск из bin/.
            for (int depth = 0; depth < 4 && current != null; depth++)
            {
                if (File.Exists(Path.Combine(current.FullName, "main.py")))
                {
                    return current.FullName;
                }

                current = current.Parent;
            }

            return null;
        }

        private static string FindPython(string root, bool console)
        {
            string[] preferred = console
                ? new[] { "python.exe", "pythonw.exe" }
                : new[] { "pythonw.exe", "python.exe" };

            string scripts = Path.Combine(root, ".venv", "Scripts");
            foreach (string name in preferred)
            {
                string candidate = Path.Combine(scripts, name);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }

            string path = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
            foreach (string raw in path.Split(';'))
            {
                string directory = raw.Trim();
                if (directory.Length == 0)
                {
                    continue;
                }

                foreach (string name in preferred)
                {
                    string candidate;
                    try
                    {
                        candidate = Path.Combine(directory, name);
                    }
                    catch (ArgumentException)
                    {
                        continue; // кривой элемент PATH — не наша проблема
                    }

                    if (File.Exists(candidate))
                    {
                        return candidate;
                    }
                }
            }

            return null;
        }

        private static bool HasFlag(string[] args, string flag)
        {
            foreach (string argument in args)
            {
                if (string.Equals(argument, flag, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }

            return false;
        }

        private static void ActivateExistingWindow()
        {
            IntPtr handle = FindWindow(null, WindowTitle);

            if (handle != IntPtr.Zero)
            {
                ShowWindow(handle, SwRestore);
                SetForegroundWindow(handle);
                return;
            }

            ShowInfo("ZERE уже запущен.\n\nЕго окно свёрнуто или ещё открывается — " +
                     "посмотрите на панели задач.");
        }

        private static void ShowError(string text)
        {
            MessageBox.Show(
                text,
                "ZERE",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error,
                MessageBoxDefaultButton.Button1,
                MessageBoxOptions.DefaultDesktopOnly);
        }

        private static void ShowInfo(string text)
        {
            MessageBox.Show(
                text,
                "ZERE",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information,
                MessageBoxDefaultButton.Button1,
                MessageBoxOptions.DefaultDesktopOnly);
        }

        private static string Tail(string path)
        {
            try
            {
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    if (stream.Length > LogTailChars)
                    {
                        stream.Seek(-LogTailChars, SeekOrigin.End);
                    }

                    using (var reader = new StreamReader(stream, Encoding.UTF8))
                    {
                        string tail = reader.ReadToEnd().Trim();
                        return tail.Length == 0 ? "(журнал пуст)" : tail;
                    }
                }
            }
            catch (Exception ex)
            {
                return "(журнал недоступен: " + ex.Message + ")";
            }
        }

        /// <summary>Потокобезопасная запись журнала: stdout и stderr — разные потоки.</summary>
        private sealed class LogWriter
        {
            private readonly object _sync = new object();
            private readonly StreamWriter _writer;

            public LogWriter(string path)
            {
                try
                {
                    string directory = Path.GetDirectoryName(path);
                    if (!string.IsNullOrEmpty(directory))
                    {
                        Directory.CreateDirectory(directory);
                    }

                    _writer = new StreamWriter(
                        new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite),
                        new UTF8Encoding(false));
                    _writer.AutoFlush = true;
                }
                catch (Exception)
                {
                    // Диск только для чтения/занят — приложение всё равно должно
                    // запуститься; журнал в этом случае недоступен.
                    _writer = null;
                }
            }

            public void Write(string line)
            {
                if (_writer == null)
                {
                    return;
                }

                lock (_sync)
                {
                    try
                    {
                        _writer.WriteLine(line);
                    }
                    catch (Exception)
                    {
                        // ошибка журнала не должна ронять ассистента
                    }
                }
            }

            public void Flush()
            {
                if (_writer == null)
                {
                    return;
                }

                lock (_sync)
                {
                    try
                    {
                        _writer.Flush();
                    }
                    catch (Exception)
                    {
                    }
                }
            }
        }
    }
}
