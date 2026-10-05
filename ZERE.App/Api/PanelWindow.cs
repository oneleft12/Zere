using System.Drawing;
using System.Windows.Forms;
using ZERE.Core.Logging;
using Microsoft.Web.WebView2.WinForms;

namespace ZERE.App.Api;

/// <summary>
/// Окно панели (этап 6 GUI-плана, вариант B): WebView2 поверх существующей SPA
/// на 127.0.0.1 — один API, один UI, переписи нет. Закрытие окна прячет его
/// в трей (сервер продолжает работать), «Выход» в трее закрывает только окно,
/// консоль ZERE жива. WebView2 Runtime недоступен — честный фолбэк в браузер.
/// </summary>
public sealed class PanelWindow : Form
{
    private readonly string _url;
    private readonly LogService _logger;
    private readonly Action<string> _fallback;
    private readonly WebView2 _webview;
    private NotifyIcon? _tray;
    private bool _exiting;

    public PanelWindow(string url, LogService logger, Action<string> fallback)
    {
        _url = url;
        _logger = logger;
        _fallback = fallback;

        Text = "ZERE";
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(1280, 840);
        BackColor = Color.FromArgb(0x0A, 0x0E, 0x14);

        _webview = new WebView2 { Dock = DockStyle.Fill };
        Controls.Add(_webview);

        // Трей: окно скрывается, ассистент и панель продолжают работать.
        var menu = new ContextMenuStrip();
        menu.Items.Add("Показать панель", null, (_, _) => ShowFromTray());
        menu.Items.Add("Свернуть в трей", null, (_, _) => Hide());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Закрыть окно", null, (_, _) => ExitWindow());
        _tray = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = "ZERE — панель",
            Visible = true,
            ContextMenuStrip = menu,
        };
        _tray.DoubleClick += (_, _) => ShowFromTray();

        Load += PanelWindow_Load;
    }

    /// <summary>Выводит окно на передний план (вызывается из STA-потока окна).</summary>
    public void ShowFromTray()
    {
        if (WindowState == FormWindowState.Minimized)
            WindowState = FormWindowState.Normal;
        Show();
        Activate();
        BringToFront();
    }

    private void ExitWindow()
    {
        _exiting = true;
        Close();
    }

    private async void PanelWindow_Load(object? sender, EventArgs e)
    {
        try
        {
            await _webview.EnsureCoreWebView2Async();
            _webview.CoreWebView2!.Navigate(_url);
        }
        catch (Exception ex)
        {
            // Нет WebView2 Runtime или сбой инициализации — уходим в браузер.
            _logger.Error($"PanelWindow: {ex.Message}");
            _fallback(_url);
            _exiting = true;
            Close();
        }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        // Крестик = свернуть в трей; реальный выход — только из меню трея.
        if (!_exiting && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            Hide();
            return;
        }

        base.OnFormClosing(e);
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        if (_tray is not null)
        {
            _tray.Visible = false;
            _tray.Dispose();
            _tray = null;
        }

        base.OnFormClosed(e);
    }
}

/// <summary>
/// Хост окна панели: единственный экземпляр; повторный вызов (команда
/// «панель» в консоли) выводит существующее окно на передний план.
/// </summary>
public static class PanelWindowHost
{
    private static volatile PanelWindow? _window;

    public static void Open(string url, LogService logger, Action<string> fallback)
    {
        var existing = _window;
        if (existing is { IsDisposed: false })
        {
            if (existing.IsHandleCreated)
            {
                try
                {
                    existing.BeginInvoke((Action)existing.ShowFromTray);
                }
                catch (Exception)
                {
                    _window = null; // окно закрывается — создадим новое
                }
            }

            // Handle ещё не создан — окно только стартует и покажет себя само.
            return;
        }

        var thread = new Thread(() =>
        {
            try
            {
                var window = new PanelWindow(url, logger, fallback);
                _window = window;
                Application.Run(window);
            }
            catch (Exception ex)
            {
                logger.Error($"PanelWindow: {ex.Message}");
                fallback(url);
            }
            finally
            {
                _window = null;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.IsBackground = true; // выход из консоли убирает и окно, и трей
        thread.Start();
    }
}
