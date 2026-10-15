# 串口通信实现规范（RS232 / RS485 / RS422）

## 1. 基础配置对照

| 参数 | 典型值 | 注意事项 |
|---|---|---|
| 波特率 | 9600 / 19200 / 38400 / 115200 | **必须与设备一致**，不一致时表现为乱码或超时 |
| 数据位 | 8（少数设备 7） | 7 位常见于老式仪表 |
| 停止位 | 1（少数 2） | |
| 校验 | None / Even / Odd | 工业仪表 Even 较多 |
| 流控 | None（绝大多数） | RS485 半双工不支持 RTS/CTS |
| 超时 | 读 500~2000ms，写 500ms | 读超时按最慢设备报文长度估算 |

**RS232 vs RS485 关键区别**：

- RS232：点对点，全双工，收发可同时。距离 ≤15m。
- RS485：总线型，**半双工**，收发需方向切换（RTS 控制）。距离可达 1200m，需 120Ω 终端电阻。
- RS485 多设备共用总线：**必须分时轮询**，禁止多个线程同时发送。上位机侧需一把总线锁。

## 2. 可复用串口传输实现

```csharp
using System;
using System.IO.Ports;
using System.Threading;
using System.Threading.Tasks;

public sealed class SerialTransport : ITransport
{
    private readonly SerialPort _port;
    private readonly ILogService _logger;
    private readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);  // 总线互斥
    private readonly object _sync = new object();
    private MemoryStream _rxBuffer = new MemoryStream(4096);
    private int _rxTotal;

    public string Name { get; }
    public bool IsOpen => _port != null && _port.IsOpen;

    public event EventHandler<TransportDataEventArgs> DataReceived;
    public event EventHandler<TransportStateEventArgs> StateChanged;

    public SerialTransport(SerialConfig cfg, ILogService logger)
    {
        _logger = logger;
        Name = cfg.PortName;

        _port = new SerialPort(cfg.PortName, cfg.BaudRate, cfg.Parity, cfg.DataBits, cfg.StopBits)
        {
            ReadTimeout = cfg.ReadTimeoutMs,
            WriteTimeout = cfg.WriteTimeoutMs,
            // ⚠️ 必须显式设置，否则 .NET 默认 1024 字节读缓冲会导致
            //    超过 1024 字节的报文被拆包，且 ReadExisting 只读到一部分
            ReadBufferSize = 4096,
            WriteBufferSize = 4096,
            Handshake = cfg.Handshake,
            DtrEnable = cfg.DtrEnable,
            RtsEnable = cfg.RtsEnable,
        };

        // ⚠️ 不要用 DataReceived 事件做业务逻辑：它在线程池回调，
        //    且不保证按行/按帧。仅用于触发接收循环。
        _port.DataReceived += OnDataReceived;
        _port.ErrorReceived += OnErrorReceived;
    }

    public Task OpenAsync(CancellationToken ct)
    {
        try
        {
            _port.Open();
            lock (_sync) { _rxBuffer.SetLength(0); _rxTotal = 0; }
            StateChanged?.Invoke(this, new TransportStateEventArgs(TransportState.Opened, null));
            _logger.Info($"串口 {Name} 已打开：{_port.BaudRate},{_port.DataBits},{_port.Parity},{_port.StopBits}");
            return Task.FromResult(true);
        }
        catch (UnauthorizedAccessException ex)
        {
            // 最常见：端口被占用
            _logger.Error(ex, $"串口 {Name} 被占用，请检查是否有其他程序或调试助手打开");
            throw new IOException($"串口 {Name} 被占用", ex);
        }
        catch (IOException ex)
        {
            _logger.Error(ex, $"串口 {Name} 不存在或驱动异常");
            throw;
        }
    }

    public Task CloseAsync()
    {
        lock (_sync)
        {
            try
            {
                if (_port.IsOpen) _port.Close();
            }
            catch (Exception ex) { _logger.Warn($"关闭串口 {Name} 异常：{ex.Message}"); }
        }
        StateChanged?.Invoke(this, new TransportStateEventArgs(TransportState.Closed, null));
        return Task.FromResult(true);
    }

    public async Task<int> SendAsync(byte[] data, CancellationToken ct)
    {
        await _sendLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (!IsOpen) throw new InvalidOperationException($"串口 {Name} 未打开");
            _port.Write(data, 0, data.Length);
            _logger.Trace($"TX[{Name}] {ToHex(data)}");
            return data.Length;
        }
        finally { _sendLock.Release(); }
    }

    /// <summary>
    /// 按期望长度接收。内部使用轮询式读取，规避 DataReceived 的不可靠性。
    /// </summary>
    public async Task<byte[]> ReceiveAsync(int expectedLength, TimeSpan timeout, CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + timeout;
        var result = new byte[expectedLength];
        int offset = 0;

        while (offset < expectedLength)
        {
            ct.ThrowIfCancellationRequested();
            if (DateTime.UtcNow > deadline)
                throw new TimeoutException($"串口 {Name} 接收超时：期望 {expectedLength} 字节，实收 {offset} 字节");

            int avail = _port.BytesToRead;
            if (avail <= 0)
            {
                await Task.Delay(5, ct).ConfigureAwait(false);
                continue;
            }

            int want = Math.Min(avail, expectedLength - offset);
            int n = _port.Read(result, offset, want);
            offset += n;
        }

        _logger.Trace($"RX[{Name}] {ToHex(result)}");
        return result;
    }

    private void OnDataReceived(object sender, SerialDataReceivedEventArgs e)
    {
        // 仅做缓冲聚合，不解析业务
        try
        {
            int avail = _port.BytesToRead;
            if (avail <= 0) return;
            var tmp = new byte[avail];
            int n = _port.Read(tmp, 0, avail);
            lock (_sync) { _rxBuffer.Write(tmp, 0, n); _rxTotal += n; }
            DataReceived?.Invoke(this, new TransportDataEventArgs(tmp, n));
        }
        catch (Exception ex) { _logger.Error(ex, $"串口 {Name} 数据接收回调异常"); }
    }

    private void OnErrorReceived(object sender, SerialErrorReceivedEventArgs e)
    {
        _logger.Warn($"串口 {Name} 硬件错误：{e.EventType}");
        if (e.EventType == SerialError.Frame || e.EventType == SerialError.Overrun)
            StateChanged?.Invoke(this, new TransportStateEventArgs(TransportState.Error, $"串口错误 {e.EventType}"));
    }

    /// <summary>丢弃输入输出缓冲，重连前必调</summary>
    public void DiscardBuffers()
    {
        lock (_sync)
        {
            try
            {
                if (_port.IsOpen) { _port.DiscardInBuffer(); _port.DiscardOutBuffer(); }
                _rxBuffer.SetLength(0); _rxTotal = 0;
            }
            catch (Exception ex) { _logger.Warn($"清空串口缓冲异常：{ex.Message}"); }
        }
    }

    public void Dispose()
    {
        try
        {
            if (_port != null)
            {
                _port.DataReceived -= OnDataReceived;
                _port.ErrorReceived -= OnErrorReceived;
                if (_port.IsOpen) _port.Close();
                _port.Dispose();
            }
        }
        catch (Exception ex) { _logger?.Warn($"释放串口异常：{ex.Message}"); }
        finally { _sendLock.Dispose(); }
    }

    private static string ToHex(byte[] d) => BitConverter.ToString(d).Replace("-", " ");
}
```

## 3. RS485 方向控制

多数 USB-RS485 转换器自动切换方向。若需手动（原生 COM 口 + RTS 控制）：

```csharp
// 发送前拉高 RTS，发送完成后延时一个字符时间再拉低
private void SendWithDirectionControl(byte[] data)
{
    _port.RtsEnable = true;                 // 进入发送态
    Thread.Sleep(1);                        // 转换器切换稳定时间
    _port.Write(data, 0, data.Length);

    // 等待最后一位移出：字符时间 = (1+数据位+校验位+停止位)/波特率
    int bitsPerChar = 1 + _port.DataBits + (_port.Parity == Parity.None ? 0 : 1) + (int)_port.StopBits;
    double charTimeMs = bitsPerChar * 1000.0 / _port.BaudRate;
    Thread.Sleep((int)Math.Ceiling(charTimeMs * data.Length) + 1);

    _port.RtsEnable = false;                // 回到接收态
}
```

> ⚠️ 这是**唯一**允许在通信线程同步 Sleep 的场景，因为时间精度依赖硬件时序。

## 4. 粘包 / 拆包处理

串口是字节流，**没有消息边界**。四种主流定界方式：

### 方式 A：固定长度（最常见于 Modbus RTU 响应）

```csharp
// Modbus RTU 读响应长度可精确计算
int expected = 5 + 2 * registerCount;   // 从站地址1 + 功能码1 + 字节数1 + 数据 + CRC2
var frame = await _transport.ReceiveAsync(expected, TimeSpan.FromMilliseconds(1000), ct);
```

### 方式 B：3.5 字符静默间隔（Modbus RTU 标准）

```csharp
// 波特率 > 19200 时固定用 1.75ms，否则按 3.5 字符时间计算
private int GetSilenceGapMs(int baudRate)
{
    if (baudRate > 19200) return 2;
    return (int)Math.Ceiling(3.5 * 11 * 1000.0 / baudRate) + 1;
}
```

实现思路：持续读入缓冲，每次收到数据后重置定时器，连续静默超过 gap 时长则认为一帧结束。

### 方式 C：帧头帧尾定界（自定义协议）

```csharp
public sealed class FrameDelimiterParser
{
    private readonly byte _head;
    private readonly byte _tail;
    private readonly List<byte> _buffer = new List<byte>(256);

    public FrameDelimiterParser(byte head, byte tail) { _head = head; _tail = tail; }

    public void Append(byte[] data) => _buffer.AddRange(data);

    public IEnumerable<byte[]> ExtractFrames()
    {
        while (true)
        {
            int start = _buffer.IndexOf(_head);
            if (start < 0) { _buffer.Clear(); yield break; }        // 无帧头，丢弃噪声

            int end = _buffer.IndexOf(_tail, start + 1);
            if (end < 0)
            {
                if (start > 0) _buffer.RemoveRange(0, start);        // 丢弃帧头前垃圾
                yield break;                                         // 帧未收完，等下次
            }

            var frame = _buffer.GetRange(start, end - start + 1).ToArray();
            _buffer.RemoveRange(0, end + 1);
            yield return frame;
        }
    }
}
```

### 方式 D：长度字段（帧内声明长度）

```csharp
// 如：AA 55 | LEN(2) | CMD(1) | PAYLOAD | CRC(2)
// 先读固定头 4 字节，再按 LEN 读剩余
var head = await _transport.ReceiveAsync(4, timeout, ct);
int payloadLen = head[2] | (head[3] << 8);
var rest = await _transport.ReceiveAsync(payloadLen + 3, timeout, ct);  // payload + cmd + crc
```

## 5. 串口踩坑清单

| 坑 | 现象 | 解法 |
|---|---|---|
| `ReadBufferSize` 未设置 | 报文 >1024 字节被截断 | 显式设 4096 或按最大报文设定 |
| 用 `ReadLine()` 读二进制 | 阻塞或读到残缺 | 用 `Read(byte[])` 按长度读 |
| `DataReceived` 里做业务 | 偶发丢帧、跨线程异常 | 只做缓冲，业务在轮询循环 |
| 关闭串口未取消订阅 | 内存泄漏、关闭后仍触发 | Dispose 中先 `-=` 再 `Close` |
| RS485 多设备并发发送 | 数据碰撞，全部超时 | 总线级 `SemaphoreSlim` 串行化 |
| 未清缓冲就重连 | 残留半帧导致解析错位 | 重连前 `DiscardInBuffer/OutBuffer` |
| 拔插 USB 转串口 | 端口号变化、句柄失效 | 按 VID/PID 或设备描述符自动匹配端口 |
| 波特率不匹配 | 乱码、CRC 全错 | 现场先用调试助手确认 |
| 未处理 `ErrorReceived` | 帧错误累积，通信静默失败 | 订阅并计数，超阈值触发重连 |
| 虚拟串口对（com0com） | 时序与实际不同，误判正常 | 完成前必须用真实设备验证 |

## 6. USB 转串口自动识别

```csharp
using System.Management;

public static class ComPortResolver
{
    /// <summary>按 VID/PID 或描述关键词查找当前分配的 COM 口号</summary>
    public static string FindPort(string vidPidOrKeyword)
    {
        using (var searcher = new ManagementObjectSearcher(
            "SELECT * FROM Win32_PnPEntity WHERE Caption LIKE '%(COM%'"))
        {
            foreach (ManagementObject obj in searcher.Get())
            {
                var caption = obj["Caption"]?.ToString();
                if (string.IsNullOrEmpty(caption)) continue;

                if (caption.IndexOf(vidPidOrKeyword, StringComparison.OrdinalIgnoreCase) < 0) continue;

                // Caption 形如 "USB-SERIAL CH340 (COM5)"
                int i = caption.LastIndexOf("(COM", StringComparison.OrdinalIgnoreCase);
                if (i < 0) continue;
                return caption.Substring(i + 1, caption.Length - i - 2);   // "COM5"
            }
        }
        return null;
    }

    public static IReadOnlyList<(string Port, string Caption)> EnumerateAll()
    {
        var list = new List<(string, string)>();
        foreach (var name in System.IO.Ports.SerialPort.GetPortNames())
        {
            using (var searcher = new ManagementObjectSearcher(
                $"SELECT * FROM Win32_PnPEntity WHERE Caption LIKE '%{name}%'"))
            {
                foreach (ManagementObject obj in searcher.Get())
                    list.Add((name, obj["Caption"]?.ToString() ?? name));
            }
        }
        return list;
    }
}
```

## 7. 串口核对项

- [ ] 端口号 / 波特率 / 数据位 / 停止位 / 校验 是否已确认（对设备手册或实测）？
- [ ] 设备是 RS232 还是 RS485？若是 485，是否需方向控制与终端电阻？
- [ ] 最大报文长度多少？`ReadBufferSize` 是否足够？
- [ ] 帧边界如何界定（固定长度 / 静默间隔 / 帧头尾 / 长度字段）？
- [ ] 读超时设置是否 ≥ 设备最慢响应时间？
- [ ] 是否处理了端口占用、拔插、端口号漂移？
- [ ] 多设备是否共用总线？是否串行化发送？
- [ ] 重连前是否清空收发缓冲？
- [ ] 是否有 CRC/校验失败计数与告警？
