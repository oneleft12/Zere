using NAudio.Wave;

namespace ZERE.Voice.Audio;

/// <summary>
/// Потоковый плеер: принимает PCM-сэмплы (s16le моно) по мере поступления
/// из TTS и играет их без ожидания полного файла — первый звук не ждёт
/// окончания синтеза.
///
/// Устройство вывода — WASAPI (см. <see cref="AudioOutputFactory"/>): у WinMM
/// лишний ресемплинг и на порядок большая задержка.
/// </summary>
public sealed class StreamPlayer : IDisposable
{
    private readonly BufferedWaveProvider _buffer;
    private readonly IWavePlayer _output;
    private volatile bool _completed;
    private volatile bool _stopped;

    public StreamPlayer(int sampleRate, float volume)
    {
        _buffer = new BufferedWaveProvider(new WaveFormat(sampleRate, 16, 1))
        {
            // Синтез быстрее реального времени, но на медленных CPU ответ LLM
            // может не успевать за воспроизведением — буфер с большим запасом.
            BufferDuration = TimeSpan.FromMinutes(2),
            DiscardOnBufferOverflow = false
        };

        _output = AudioOutputFactory.Create();
        _output.Volume = Math.Clamp(volume, 0f, 1f);
        _output.Init(_buffer);
        _output.Play();
    }

    /// <summary>Добавляет очередной кусок PCM из потока TTS. Потокобезопасно.</summary>
    public void AddSamples(byte[] data, int offset, int count)
    {
        if (_stopped)
            return;

        _buffer.AddSamples(data, offset, count);
    }

    /// <summary>Вызывается, когда TTS отдал всё аудио.</summary>
    public void Complete() => _completed = true;

    /// <summary>
    /// Ждёт, пока дочитается весь буфер. Бросает OperationCanceledException при отмене.
    /// </summary>
    public async Task WaitUntilFinishedAsync(CancellationToken ct)
    {
        while (!_stopped && !(_completed && _buffer.BufferedBytes == 0))
        {
            ct.ThrowIfCancellationRequested();
            await Task.Delay(50, ct).ConfigureAwait(false);
        }

        if (_stopped)
            return;

        // Хвост мог остаться в буфере устройства WaveOut — даём ему проиграться.
        await Task.Delay(300, ct).ConfigureAwait(false);
    }

    public void Stop()
    {
        _stopped = true;
        try { _output.Stop(); } catch { /* плеер уже остановлен */ }
    }

    public void Dispose()
    {
        Stop();
        try { _output.Dispose(); } catch { }
        GC.SuppressFinalize(this);
    }
}
