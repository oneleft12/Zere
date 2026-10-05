using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace JARVIS.Voice.Audio;

/// <summary>
/// Создание устройства вывода для NAudio.
///
/// Предпочитается <see cref="WasapiOut"/>: это современный тракт Windows
/// (shared mode), у которого нет лишнего ресемплинга и задержка на порядок
/// меньше, чем у WinMM. Замеры на Sennheiser USB headset (44100 Гц):
///
///     MME (WaveOutEvent)  180 мс
///     WASAPI               22 мс
///
/// WinMM оставлен как откат: если WASAPI-устройство недоступно (нет драйвера,
/// устройство занято эксклюзивно), голос должен продолжать работать.
/// </summary>
public static class AudioOutputFactory
{
    /// <summary>Задержка WASAPI в миллисекундах (компромисс отзывчивость/стабильность).</summary>
    private const int WasapiLatencyMs = 100;

    private static bool _wasapiUnavailable;

    /// <summary>
    /// Устройство вывода: WASAPI на устройстве по умолчанию, иначе WinMM.
    /// Никогда не бросает исключение — только возвращает рабочий вариант.
    /// </summary>
    public static IWavePlayer Create()
    {
        if (!_wasapiUnavailable)
        {
            try
            {
                using var enumerator = new MMDeviceEnumerator();
                var device = enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);

                // useEventSync: true — ожидание по событию вместо опроса,
                // меньше нагрузка на CPU при потоковой озвучке.
                return new WasapiOut(device, AudioClientShareMode.Shared, true, WasapiLatencyMs);
            }
            catch (Exception ex)
            {
                // Помечаем один раз: не засоряем лог на каждое предложение.
                _wasapiUnavailable = true;
                Console.WriteLine($"[AudioPlayer] WASAPI недоступен ({ex.Message}) — откат на WinMM.");
            }
        }

        return new WaveOutEvent
        {
            DesiredLatency = 120
        };
    }
}
