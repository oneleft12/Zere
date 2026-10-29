// ZERE — установщик приложения (ZereSetup.exe).
//
// Почему свой установщик, а не Inno Setup: на Windows 11 включён Smart App
// Control (WDAC), и он блокирует свежесобранный неподписанный Setup.exe —
// двойной клик заканчивается «заблокирован политикой Device Guard».
// Файлы, собранные системным csc.exe из .NET Framework, этот фильтр
// пропускает (как и zere.exe), поэтому установщик собирается им же.
//
// Что делает установщик:
//   1. Распаковывает встроенный архив дистрибутива в папку установки
//      (по умолчанию %LOCALAPPDATA%\Programs\ZERE, права администратора
//      не нужны);
//   2. Запускает installer\install.ps1 — Python, зависимости, Ollama и
//      модель, голосовые модели, лаунчер, ярлыки (ярлык ведёт на zere.exe);
//   3. Регистрирует деинсталлятор в «Установка и удаление программ»;
//   4. По желанию запускает zere.exe — окно ZERE, а не браузер.
//
// Код намеренно на C# 5: csc из .NET Framework 4.x не понимает интерполяцию
// строк и null-условный оператор, а SDK на целевой машине может не быть.
//
// Сборка: installer\build-installer.ps1 (stage из git archive + csc).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("ZERE Setup")]
[assembly: AssemblyDescription("ZERE — установщик персонального AI-ассистента")]
[assembly: AssemblyProduct("ZERE")]
[assembly: AssemblyCompany("ZERE Project")]
[assembly: AssemblyVersion("1.9.0.0")]
[assembly: AssemblyFileVersion("1.9.0.0")]

namespace ZereSetup
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            Options options = Options.Parse(args);

            if (options.Help)
            {
                ShowHelp();
                return 0;
            }

            if (options.Uninstall)
            {
                return Uninstaller.Run(options);
            }

            if (options.Silent)
            {
                return Installer.Run(options, null);
            }

            using (SetupForm form = new SetupForm(options))
            {
                Application.Run(form);
                return form.ResultCode;
            }
        }

        private static void ShowHelp()
        {
            string text =
                "ZERE — установщик.\r\n\r\n" +
                "  ZereSetup.exe                    мастер установки\r\n" +
                "  ZereSetup.exe /SILENT [/DIR=ПУТЬ] [/NOLAUNCH]\r\n" +
                "                                   тихая установка (без окна)\r\n" +
                "  ZereSetup.exe /UNINSTALL [/PURGEDATA]\r\n" +
                "                                   удаление ZERE\r\n\r\n" +
                "По умолчанию ZERE ставится в %LOCALAPPDATA%\\Programs\\ZERE\r\n" +
                "и запускается как zere.exe (окно приложения, без браузера и консоли).";
            MessageBox.Show(text, "ZERE Setup", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
    }

    /// <summary>Разобранная командная строка установщика.</summary>
    internal sealed class Options
    {
        public string Prefix;
        public bool Silent;
        public bool NoLaunch;
        public bool NoShortcuts;
        /// <summary>Не ставить Ollama: ZERE работает через облачный ключ.</summary>
        public bool SkipOllama;
        public bool Uninstall;
        public bool PurgeData;
        public bool Help;

        public static Options Parse(string[] args)
        {
            Options options = new Options();
            options.Prefix = Installer.DefaultPrefix();

            foreach (string raw in args)
            {
                if (raw == null) { continue; }

                string argument = raw.Trim();
                if (argument.Length == 0) { continue; }

                string upper = argument.ToUpperInvariant();

                if (upper == "/SILENT" || upper == "/VERYSILENT" || upper == "/S" || upper == "/QUIET")
                {
                    options.Silent = true;
                }
                else if (upper == "/NOLAUNCH")
                {
                    options.NoLaunch = true;
                }
                else if (upper == "/NOSHORTCUTS")
                {
                    options.NoShortcuts = true;
                }
                else if (upper == "/SKIPOLLAMA" || upper == "/NOOLLAMA" || upper == "/WITHOUTOLLAMA")
                {
                    options.SkipOllama = true;
                }
                else if (upper == "/UNINSTALL" || upper == "/REMOVE")
                {
                    options.Uninstall = true;
                }
                else if (upper == "/PURGEDATA")
                {
                    options.PurgeData = true;
                }
                else if (upper == "/?" || upper == "/HELP" || upper == "-H" || upper == "--HELP")
                {
                    options.Help = true;
                }
                else if (StartsWithArgument(argument, "/DIR") || StartsWithArgument(argument, "/PREFIX"))
                {
                    options.Prefix = ArgumentValue(argument);
                }
                else if (StartsWithArgument(argument, "/UNINSTALLDIR") || StartsWithArgument(argument, "/APP"))
                {
                    // Каталог, из которого надо удалять (передаёт UninstallString).
                    options.Prefix = ArgumentValue(argument);
                }
            }

            if (string.IsNullOrWhiteSpace(options.Prefix))
            {
                options.Prefix = Installer.DefaultPrefix();
            }

            options.Prefix = Path.GetFullPath(options.Prefix.Trim().TrimEnd('"'));
            return options;
        }

        private static bool StartsWithArgument(string argument, string name)
        {
            if (!argument.StartsWith(name, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            return argument.Length == name.Length || argument[name.Length] == '=' || argument[name.Length] == ':';
        }

        private static string ArgumentValue(string argument)
        {
            int index = argument.IndexOf('=');
            if (index < 0) { index = argument.IndexOf(':'); }
            if (index < 0 || index + 1 >= argument.Length) { return string.Empty; }

            return argument.Substring(index + 1).Trim().Trim('"');
        }
    }

    /// <summary>Общая часть установки и удаления.</summary>
    internal static class Installer
    {
        public const string AppName = "ZERE";
        public const string UninstallKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\ZERE";
        public const string PayloadResource = "payload.zip";

        public static string DefaultPrefix()
        {
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(local, "Programs", "ZERE");
        }

        public static string Version()
        {
            Version version = Assembly.GetExecutingAssembly().GetName().Version;
            return version.Major + "." + version.Minor + "." + version.Build;
        }

        /// <summary>Тихая установка: без окон, результат — код возврата.</summary>
        public static int Run(Options options, Action<string> log)
        {
            try
            {
                int code = Install(options, log);
                return code;
            }
            catch (Exception ex)
            {
                Report(log, "Ошибка установки: " + ex.Message);
                return 1;
            }
        }

        private static int Install(Options options, Action<string> log)
        {
            string prefix = options.Prefix;

            Report(log, "Папка установки: " + prefix);

            if (!PrepareDirectory(prefix))
            {
                Report(log, "Нет прав на запись в папку: " + prefix);
                return 1;
            }

            if (!ExtractPayload(prefix, log))
            {
                Report(log, "Не удалось распаковать файлы дистрибутива.");
                return 1;
            }

            int code = RunInstallScript(prefix, options, log);
            if (code != 0)
            {
                Report(log, "Настройка завершилась с ошибкой (код " + code +
                            "). Подробности: " + Path.Combine(prefix, "installer", "install-log.txt"));
                return code;
            }

            RegisterUninstall(prefix);
            WriteUninstaller(prefix);
            Report(log, "Установка завершена: " + prefix);
            return 0;
        }

        private static bool PrepareDirectory(string prefix)
        {
            try
            {
                Directory.CreateDirectory(prefix);
                string probe = Path.Combine(prefix, ".zere-write-test");
                File.WriteAllText(probe, "ok");
                File.Delete(probe);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>Распаковка встроенного архива дистрибутива.</summary>
        public static bool ExtractPayload(string prefix, Action<string> log)
        {
            Assembly assembly = Assembly.GetExecutingAssembly();
            using (Stream stream = assembly.GetManifestResourceStream(PayloadResource))
            {
                if (stream == null)
                {
                    Report(log, "В установщике нет архива дистрибутива (" + PayloadResource + ").");
                    return false;
                }

                string root = Path.GetFullPath(prefix);
                if (!root.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal))
                {
                    root = root + Path.DirectorySeparatorChar;
                }

                using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read))
                {
                    int total = archive.Entries.Count;
                    int index = 0;

                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        index++;
                        string name = entry.FullName.Replace('/', Path.DirectorySeparatorChar);

                        if (string.IsNullOrEmpty(name)) { continue; }

                        string target = Path.GetFullPath(Path.Combine(prefix, name));

                        // Защита от «..\» в архиве: писать можно только внутрь папки установки.
                        if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                        {
                            Report(log, "Пропущен подозрительный путь в архиве: " + entry.FullName);
                            continue;
                        }

                        if (name.EndsWith(Path.DirectorySeparatorChar.ToString(), StringComparison.Ordinal))
                        {
                            Directory.CreateDirectory(target);
                            continue;
                        }

                        string directory = Path.GetDirectoryName(target);
                        if (!string.IsNullOrEmpty(directory))
                        {
                            Directory.CreateDirectory(directory);
                        }

                        using (Stream source = entry.Open())
                        using (FileStream destination = new FileStream(target, FileMode.Create, FileAccess.Write, FileShare.None))
                        {
                            source.CopyTo(destination);
                        }

                        if (index % 200 == 0)
                        {
                            Report(log, "Распаковано файлов: " + index + " из " + total);
                        }
                    }
                }
            }

            Report(log, "Файлы распакованы.");
            return true;
        }

        /// <summary>Запуск installer\install.ps1 — вся настройка окружения.</summary>
        private static int RunInstallScript(string prefix, Options options, Action<string> log)
        {
            string script = Path.Combine(prefix, "installer", "install.ps1");
            if (!File.Exists(script))
            {
                Report(log, "В дистрибутиве нет installer\\install.ps1: " + script);
                return 1;
            }

            StringBuilder arguments = new StringBuilder();
            arguments.Append("-NoProfile -ExecutionPolicy Bypass -File \"");
            arguments.Append(script);
            arguments.Append("\" -Prefix \"");
            arguments.Append(prefix);
            arguments.Append("\" -Edition python -Yes -NoLaunch");
            if (options.NoShortcuts)
            {
                arguments.Append(" -SkipShortcuts");
            }
            if (options.SkipOllama)
            {
                // ZERE работает без локальной модели: облачный ключ вводится в
                // панели (экран «ИИ»). Ollama не ставим и не трогаем.
                arguments.Append(" -SkipOllama");
            }

            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = PowerShellPath();
            startInfo.Arguments = arguments.ToString();
            startInfo.WorkingDirectory = prefix;
            // Тихая установка — без окна (вывод всё равно в installer\install-log.txt),
            // обычная — с видимым окном консоли: по нему видно ход pip и загрузок.
            startInfo.UseShellExecute = !options.Silent;
            startInfo.CreateNoWindow = options.Silent;

            Report(log, options.SkipOllama
                ? "Настройка окружения: Python, зависимости, голосовые модели (без Ollama)…"
                : "Настройка окружения: Python, зависимости, Ollama, голосовые модели…");
            Report(log, "Подробный журнал: " + Path.Combine(prefix, "installer", "install-log.txt"));

            try
            {
                using (Process process = Process.Start(startInfo))
                {
                    if (process == null)
                    {
                        Report(log, "Не удалось запустить install.ps1.");
                        return 1;
                    }

                    process.WaitForExit();
                    return process.ExitCode;
                }
            }
            catch (Exception ex)
            {
                Report(log, "Ошибка запуска install.ps1: " + ex.Message);
                return 1;
            }
        }

        public static string PowerShellPath()
        {
            string system = Environment.GetFolderPath(Environment.SpecialFolder.System);
            return Path.Combine(system, "WindowsPowerShell\\v1.0\\powershell.exe");
        }

        /// <summary>Запись в «Установка и удаление программ» (HKCU, без прав админа).</summary>
        public static void RegisterUninstall(string prefix)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallKeyPath))
                {
                    if (key == null) { return; }

                    string uninstaller = Path.Combine(prefix, "ZereUninstall.exe");
                    string icon = Path.Combine(prefix, "zere.exe");

                    key.SetValue("DisplayName", AppName);
                    key.SetValue("DisplayVersion", Version());
                    key.SetValue("Publisher", "ZERE Project");
                    key.SetValue("InstallLocation", prefix);
                    key.SetValue("DisplayIcon", File.Exists(icon) ? icon : uninstaller);
                    key.SetValue("UninstallString", "\"" + uninstaller + "\" /UNINSTALL \"/DIR=" + prefix + "\"");
                    key.SetValue("QuietUninstallString", "\"" + uninstaller + "\" /UNINSTALL /SILENT \"/DIR=" + prefix + "\"");
                    key.SetValue("EstimatedSize", EstimateSizeKb(prefix), RegistryValueKind.DWord);
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                }
            }
            catch (Exception)
            {
                // Запись в реестр — удобство, а не условие работы: установка уже прошла.
            }
        }

        public static void RemoveUninstallKey()
        {
            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(UninstallKeyPath, false);
            }
            catch (Exception)
            {
            }
        }

        /// <summary>Копия установщика рядом с программой — для деинсталляции.</summary>
        public static void WriteUninstaller(string prefix)
        {
            try
            {
                string self = Assembly.GetExecutingAssembly().Location;
                string target = Path.Combine(prefix, "ZereUninstall.exe");
                if (string.Equals(self, target, StringComparison.OrdinalIgnoreCase))
                {
                    return;
                }

                File.Copy(self, target, true);
            }
            catch (Exception)
            {
            }
        }

        private static int EstimateSizeKb(string prefix)
        {
            try
            {
                long bytes = 0;
                foreach (string file in Directory.GetFiles(prefix, "*", SearchOption.AllDirectories))
                {
                    try { bytes += new FileInfo(file).Length; } catch (Exception) { }
                }

                long kb = bytes / 1024;
                return kb > int.MaxValue ? int.MaxValue : (int)kb;
            }
            catch (Exception)
            {
                return 0;
            }
        }

        public static void Launch(string prefix)
        {
            string exe = Path.Combine(prefix, "zere.exe");
            if (!File.Exists(exe))
            {
                return;
            }

            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = exe;
            startInfo.WorkingDirectory = prefix;
            startInfo.UseShellExecute = true;
            Process.Start(startInfo);
        }

        private static void Report(Action<string> log, string text)
        {
            if (log != null)
            {
                log(text);
            }
        }
    }

    /// <summary>Удаление ZERE: uninstall.ps1 + запись в реестре + папка установки.</summary>
    internal static class Uninstaller
    {
        public static int Run(Options options)
        {
            string prefix = options.Prefix;

            if (!options.Silent)
            {
                string question =
                    "Удалить ZERE из папки:\r\n" + prefix + "\r\n\r\n" +
                    "Будут удалены окружение Python, голосовые модели и ярлыки.\r\n" +
                    "Память, история диалогов и настройки сохранятся.";
                DialogResult answer = MessageBox.Show(
                    question,
                    "Удаление ZERE",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question,
                    MessageBoxDefaultButton.Button2);

                if (answer != DialogResult.Yes)
                {
                    return 0;
                }
            }

            RunScript(prefix, options);

            Installer.RemoveUninstallKey();
            RemoveShortcuts();

            // Процесс нельзя удалить вместе с папкой — просим cmd сделать это
            // после выхода установщика.
            ScheduleFolderRemoval(prefix);

            if (!options.Silent)
            {
                MessageBox.Show(
                    "ZERE удалён.\r\n\r\nПамять и история сохранены в папке программы, " +
                    "если вы их не удаляли.",
                    "ZERE",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }

            return 0;
        }

        private static void RunScript(string prefix, Options options)
        {
            string script = Path.Combine(prefix, "installer", "uninstall.ps1");
            if (!File.Exists(script))
            {
                return;
            }

            string arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script +
                               "\" -Prefix \"" + prefix + "\" -Yes -RemoveAssets";
            if (options.PurgeData)
            {
                arguments += " -PurgeData";
            }

            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = Installer.PowerShellPath();
            startInfo.Arguments = arguments;
            startInfo.WorkingDirectory = prefix;
            startInfo.UseShellExecute = !options.Silent;
            startInfo.CreateNoWindow = options.Silent;

            try
            {
                using (Process process = Process.Start(startInfo))
                {
                    if (process != null)
                    {
                        process.WaitForExit();
                    }
                }
            }
            catch (Exception)
            {
            }
        }

        private static void RemoveShortcuts()
        {
            try
            {
                string desktop = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
                string programs = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                string startMenu = Path.Combine(programs, "ZERE");

                DeleteFile(Path.Combine(desktop, "ZERE.lnk"));
                DeleteFile(Path.Combine(desktop, "ZERE - panel.url"));
                DeleteFile(Path.Combine(startMenu, "ZERE.lnk"));
                DeleteFile(Path.Combine(startMenu, "ZERE - panel.url"));

                if (Directory.Exists(startMenu))
                {
                    Directory.Delete(startMenu, true);
                }
            }
            catch (Exception)
            {
            }
        }

        private static void DeleteFile(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                }
            }
            catch (Exception)
            {
            }
        }

        private static void ScheduleFolderRemoval(string prefix)
        {
            try
            {
                string command = "timeout /t 2 /nobreak > nul & rmdir /s /q \"" + prefix + "\"";
                ProcessStartInfo startInfo = new ProcessStartInfo();
                startInfo.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe");
                startInfo.Arguments = "/c " + command;
                startInfo.CreateNoWindow = true;
                startInfo.UseShellExecute = false;
                startInfo.WindowStyle = ProcessWindowStyle.Hidden;
                Process.Start(startInfo);
            }
            catch (Exception)
            {
            }
        }
    }

    /// <summary>Мастер установки: папка, галочки, ход установки, итог.</summary>
    internal sealed class SetupForm : Form
    {
        private readonly Options _options;
        private readonly TextBox _pathBox;
        private readonly CheckBox _desktopShortcut;
        private readonly CheckBox _skipOllama;
        private readonly Label _ollamaHint;
        private readonly CheckBox _launchApp;
        private readonly TextBox _log;
        private readonly ProgressBar _progress;
        private readonly Button _installButton;
        private readonly Button _cancelButton;

        private int _resultCode = 1;
        private bool _installed;

        public SetupForm(Options options)
        {
            _options = options;

            Text = "Установка ZERE";
            ClientSize = new Size(620, 484);
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            Font = new Font("Segoe UI", 9f);

            Label title = new Label();
            title.Text = "ZERE — персональный AI-ассистент";
            title.Font = new Font("Segoe UI", 14f, FontStyle.Bold);
            title.AutoSize = true;
            title.Location = new Point(20, 18);
            Controls.Add(title);

            Label subtitle = new Label();
            subtitle.Text = "Установка без прав администратора. Приложение откроется одним окном (zere.exe).";
            subtitle.AutoSize = true;
            subtitle.ForeColor = Color.DimGray;
            subtitle.Location = new Point(22, 52);
            Controls.Add(subtitle);

            Label pathLabel = new Label();
            pathLabel.Text = "Папка установки:";
            pathLabel.AutoSize = true;
            pathLabel.Location = new Point(22, 92);
            Controls.Add(pathLabel);

            _pathBox = new TextBox();
            _pathBox.Text = options.Prefix;
            _pathBox.Location = new Point(22, 112);
            _pathBox.Width = 480;
            Controls.Add(_pathBox);

            Button browse = new Button();
            browse.Text = "Обзор…";
            browse.Location = new Point(510, 111);
            browse.Width = 84;
            browse.Click += OnBrowse;
            Controls.Add(browse);

            _desktopShortcut = new CheckBox();
            _desktopShortcut.Text = "Создать ярлык на рабочем столе";
            _desktopShortcut.Checked = true;
            _desktopShortcut.AutoSize = true;
            _desktopShortcut.Location = new Point(22, 146);
            Controls.Add(_desktopShortcut);

            _skipOllama = new CheckBox();
            _skipOllama.Text = "Установить без Ollama";
            _skipOllama.Checked = options.SkipOllama;
            _skipOllama.AutoSize = true;
            _skipOllama.Location = new Point(22, 170);
            _skipOllama.CheckedChanged += OnSkipOllamaChanged;
            Controls.Add(_skipOllama);

            _ollamaHint = new Label();
            _ollamaHint.AutoSize = true;
            _ollamaHint.ForeColor = Color.DimGray;
            _ollamaHint.Location = new Point(40, 192);
            _ollamaHint.Text = "ZERE запустится без локальной модели: нужен облачный ключ (панель → «ИИ»).";
            Controls.Add(_ollamaHint);

            _launchApp = new CheckBox();
            _launchApp.Text = "Запустить ZERE после установки";
            _launchApp.Checked = true;
            _launchApp.AutoSize = true;
            _launchApp.Location = new Point(22, 216);
            Controls.Add(_launchApp);

            _progress = new ProgressBar();
            _progress.Location = new Point(22, 248);
            _progress.Width = 572;
            _progress.Height = 18;
            _progress.Style = ProgressBarStyle.Marquee;
            _progress.MarqueeAnimationSpeed = 0;
            Controls.Add(_progress);

            _log = new TextBox();
            _log.Multiline = true;
            _log.ReadOnly = true;
            _log.ScrollBars = ScrollBars.Vertical;
            _log.BackColor = Color.White;
            _log.Location = new Point(22, 274);
            _log.Size = new Size(572, 160);
            _log.Text = "Нажмите «Установить». Займёт несколько минут: скачиваются модели и зависимости.";
            Controls.Add(_log);

            _installButton = new Button();
            _installButton.Text = "Установить";
            _installButton.Location = new Point(416, 442);
            _installButton.Width = 90;
            _installButton.Click += OnInstall;
            Controls.Add(_installButton);

            _cancelButton = new Button();
            _cancelButton.Text = "Отмена";
            _cancelButton.Location = new Point(512, 442);
            _cancelButton.Width = 84;
            _cancelButton.DialogResult = DialogResult.Cancel;
            Controls.Add(_cancelButton);

            OnSkipOllamaChanged(null, EventArgs.Empty);

            AcceptButton = _installButton;
            CancelButton = _cancelButton;
        }

        public int ResultCode
        {
            get { return _resultCode; }
        }

        private void OnBrowse(object sender, EventArgs e)
        {
            using (FolderBrowserDialog dialog = new FolderBrowserDialog())
            {
                dialog.Description = "Куда установить ZERE";
                dialog.SelectedPath = _pathBox.Text;
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    _pathBox.Text = Path.Combine(dialog.SelectedPath, "ZERE");
                }
            }
        }

        private void OnInstall(object sender, EventArgs e)
        {
            if (_installed)
            {
                Close();
                return;
            }

            string prefix;
            try
            {
                prefix = Path.GetFullPath(_pathBox.Text.Trim().Trim('"'));
            }
            catch (Exception)
            {
                MessageBox.Show(this, "Некорректный путь установки.", "ZERE", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            if (prefix.Length < 4 || Directory.GetParent(prefix) == null)
            {
                MessageBox.Show(this, "Выберите папку внутри профиля пользователя, например " +
                                      Installer.DefaultPrefix(), "ZERE", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            _options.Prefix = prefix;
            _options.NoShortcuts = !_desktopShortcut.Checked;
            _options.SkipOllama = _skipOllama.Checked;

            SetBusy(true);
            Append("Папка установки: " + prefix);
            Application.DoEvents();

            bool ok = false;
            int code = 1;
            try
            {
                code = Installer.Run(_options, Append);
                ok = code == 0;
            }
            catch (Exception ex)
            {
                Append("Ошибка установки: " + ex.Message);
            }

            _resultCode = ok ? 0 : code;
            SetBusy(false);

            if (ok)
            {
                _installed = true;
                _installButton.Text = "Закрыть";
                _pathBox.Enabled = false;
                _desktopShortcut.Enabled = false;
                _skipOllama.Enabled = false;
                _launchApp.Enabled = false;
                Append("Готово. Запуск ZERE — ярлык ZERE или zere.exe в папке установки.");

                if (_launchApp.Checked)
                {
                    try { Installer.Launch(prefix); } catch (Exception ex) { Append("Не удалось запустить ZERE: " + ex.Message); }
                }
            }
            else
            {
                Append("Установка не завершена. Журнал: " + Path.Combine(prefix, "installer", "install-log.txt"));
                MessageBox.Show(
                    this,
                    "Установка завершилась с ошибкой (код " + code + ").\r\n\r\n" +
                    "Подробности — в файле installer\\install-log.txt в папке установки.\r\n" +
                    "Часто помогает повторный запуск установщика: уже поставленное пропускается.",
                    "ZERE",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
        }

        private void SetBusy(bool busy)
        {
            _progress.MarqueeAnimationSpeed = busy ? 30 : 0;
            _installButton.Enabled = !busy;
            _pathBox.Enabled = !busy && !_installed;
            _desktopShortcut.Enabled = !busy && !_installed;
            _skipOllama.Enabled = !busy && !_installed;
            _launchApp.Enabled = !busy && !_installed;
            Cursor = busy ? Cursors.WaitCursor : Cursors.Default;
        }

        private void OnSkipOllamaChanged(object sender, EventArgs e)
        {
            // Пояснение показываем только когда галочка стоит: иначе строка
            // «нужен облачный ключ» пугает тех, кто ставит Ollama.
            _ollamaHint.Visible = _skipOllama.Checked;
        }

        private void Append(string line)
        {
            if (InvokeRequired)
            {
                BeginInvoke(new Action<string>(Append), new object[] { line });
                return;
            }

            _log.AppendText(DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture) + "  " + line + "\r\n");
            Application.DoEvents();
        }
    }
}
