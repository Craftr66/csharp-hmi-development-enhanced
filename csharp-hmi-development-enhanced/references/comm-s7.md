# 西门子 S7 通信实现规范

## 1. 协议与库选型

| 库 | 支持型号 | 说明 |
|---|---|---|
| `S7.Net` | S7-200/300/400/1200/1500 | **推荐**，开源，API 简洁 |
| `Sharp7` | S7-300/400/1200/1500 | 更底层，性能好，需自行封装 |
| `Snap7` (C++/C# 绑定) | 全系列 | 功能最全，需部署原生 DLL |
| `libnodave` | 老型号 | 已较少使用 |

.NET Framework 4.8 建议用 `S7.Net`（有 net40/net45 目标）。

```xml
<PackageReference Include="S7netplus" Version="0.20.0" />
```

## 2. 前置条件（**最容易忽略且必查**）

| 条件 | 说明 |
|---|---|
| PLC 开启 PUT/GET | 1200/1500 需在 TIA Portal 中勾选"允许来自远程对象的 PUT/GET 通信访问"，**否则读不到任何数据** |
| 关闭"优化的块访问" | DB 块必须取消"优化的块访问"，否则无固定偏移地址 |
| 机架号 / 槽号 | S7-300/400：通常 Rack=0, Slot=2；S7-1200/1500：Rack=0, Slot=1 |
| 端口 | 默认 102（ISO-on-TCP） |
| 网段可达 | 上位机与 PLC 同网段，`ping` 通 |
| 连接资源数 | PLC 有最大连接数限制，多客户端会失败 |

> ⚠️ **最常见的"连不上/读不到"原因排序**：① 未开 PUT/GET；② DB 未取消优化访问；③ 机架槽号错误；④ 防火墙。

## 3. 基础实现（基于 S7.Net）

```csharp
using S7.Net;
using System;
using System.Threading;
using System.Threading.Tasks;

public sealed class S7PlcDriver : IDeviceDriver<S7Protocol, double>
{
    private readonly Plc _plc;
    private readonly S7Config _cfg;
    private readonly ILogService _logger;
    private readonly SemaphoreSlim _ioLock = new SemaphoreSlim(1, 1);   // S7 连接非线程安全
    private readonly ExponentialBackoff _backoff = new ExponentialBackoff(1000, 30000);

    public string DeviceId { get; }
    public DeviceState State { get; private set; } = DeviceState.Disconnected;

    public S7PlcDriver(S7Config cfg, ILogService logger)
    {
        _cfg = cfg;
        _logger = logger;
        DeviceId = cfg.Name;

        CpuType cpu = ParseCpuType(cfg.CpuType);
        _plc = new Plc(cpu, cfg.IpAddress, cfg.Rack, cfg.Slot);
        _plc.ReadTimeout = cfg.ReadTimeoutMs;
        _plc.WriteTimeout = cfg.WriteTimeoutMs;
    }

    private static CpuType ParseCpuType(string s) => s.ToUpperInvariant() switch
    {
        "S7200"   => CpuType.S7200,
        "S7300"   => CpuType.S7300,
        "S7400"   => CpuType.S7400,
        "S71200"  => CpuType.S71200,
        "S71500"  => CpuType.S71500,
        _ => throw new ArgumentException($"不支持的 CPU 型号：{s}")
    };

    public async Task ConnectAsync(CancellationToken ct)
    {
        await _ioLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (_plc.IsConnected) { State = DeviceState.Connected; return; }

            State = DeviceState.Connecting;

            // ⚠️ S7.Net 的 Open 是同步阻塞的，必须放到线程池
            await Task.Run(() => _plc.Open(), ct).ConfigureAwait(false);

            if (!_plc.IsConnected)
                throw new IOException($"连接到 {_cfg.IpAddress} 失败");

            _backoff.Reset();
            State = DeviceState.Connected;
            _logger.Info($"S7 {_cfg.Name} 已连接（{_cfg.CpuType} {_cfg.IpAddress} R{_cfg.Rack}/S{_cfg.Slot}）");
        }
        catch (Exception ex)
        {
            State = DeviceState.Faulted;
            _logger.Error(ex, $"S7 {_cfg.Name} 连接失败");
            throw;
        }
        finally { _ioLock.Release(); }
    }

    public Task DisconnectAsync()
    {
        try { if (_plc.IsConnected) _plc.Close(); } catch (Exception ex) { _logger.Warn($"关闭 S7 异常：{ex.Message}"); }
        State = DeviceState.Disconnected;
        return Task.CompletedTask;
    }

    public async Task<double> ReadAsync(string tag, CancellationToken ct)
    {
        var def = _cfg.Tags.FirstOrDefault(t => t.Name == tag)
                  ?? throw new ArgumentException($"未定义标签：{tag}");

        await _ioLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            EnsureConnected();
            // Read 是同步 IO，必须 Task.Run 包裹
            object raw = await Task.Run(() => _plc.Read(def.Address), ct).ConfigureAwait(false);

            if (raw == null) throw new ProtocolException($"读取 {tag}({def.Address}) 返回 null");

            double value = Convert.ToDouble(raw);
            _logger.Trace($"S7 读 {tag} = {value}");

            // 量纲换算
            return value * def.Scale + def.Offset;
        }
        finally { _ioLock.Release(); }
    }

    public async Task WriteAsync(string tag, double value, CancellationToken ct)
    {
        var def = _cfg.Tags.FirstOrDefault(t => t.Name == tag)
                  ?? throw new ArgumentException($"未定义标签：{tag}");
        if (def.Access != TagAccess.ReadWrite)
            throw new InvalidOperationException($"标签 {tag} 不可写");

        // 反换算 + 范围校验
        double raw = (value - def.Offset) / def.Scale;
        if (def.MinValue.HasValue && value < def.MinValue.Value)
            throw new ArgumentOutOfRangeException(tag, $"低于下限 {def.MinValue}");
        if (def.MaxValue.HasValue && value > def.MaxValue.Value)
            throw new ArgumentOutOfRangeException(tag, $"高于上限 {def.MaxValue}");

        await _ioLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            EnsureConnected();
            object typed = ConvertToS7Type(raw, def.DataType);
            await Task.Run(() => _plc.Write(def.Address, typed), ct).ConfigureAwait(false);
            _logger.Info($"S7 写 {tag} = {value}（原始值 {raw}）");
        }
        finally { _ioLock.Release(); }
    }

    private static object ConvertToS7Type(double raw, string dataType) => dataType.ToUpperInvariant() switch
    {
        "BOOL"  => raw != 0,
        "BYTE"  => (byte)raw,
        "INT"   => (short)raw,
        "WORD"  => (ushort)raw,
        "DINT"  => (int)raw,
        "DWORD" => (uint)raw,
        "REAL"  => (float)raw,
        "LREAL" => raw,
        _ => throw new NotSupportedException($"不支持的数据类型：{dataType}")
    };

    private void EnsureConnected()
    {
        if (!_plc.IsConnected) throw new IOException($"S7 {_cfg.Name} 未连接");
    }
}
```

## 4. 批量读取优化（性能核心）

**逐点读取极慢**（每点一次往返，约 20-50ms）。必须用连续块读取。

```csharp
public sealed class S7BlockReader
{
    private readonly Plc _plc;
    private readonly ILogService _logger;

    /// <summary>
    /// 合并相邻地址为连续块，一次读取。返回 字节数组。
    /// 返回值为 (起始地址, 数据字节)
    /// </summary>
    public async Task<List<(string Start, byte[] Data)>> ReadBlocksAsync(
        IEnumerable<S7TagDef> tags, CancellationToken ct)
    {
        var blocks = PlanBlocks(tags);
        var results = new List<(string, byte[])>();

        foreach (var block in blocks)
        {
            ct.ThrowIfCancellationRequested();
            // 单次读取长度上限：S7-300/400 约 222 字节，S7-1200/1500 约 8192 字节
            int maxLen = _logger != null && block.MaxLength > 0 ? block.MaxLength : 200;
            int offset = 0;

            while (offset < block.Length)
            {
                int len = Math.Min(maxLen, block.Length - offset);
                string addr = BuildAddress(block.DbNumber, block.StartByte + offset, len);

                var data = await Task.Run(() => _plc.ReadBytes(DataType.DataBlock,
                    block.DbNumber, block.StartByte + offset, len), ct).ConfigureAwait(false);

                results.Add((addr, data));
                offset += len;
            }
        }
        return results;
    }

    /// <summary>把标签按 DB 块与地址连续性归并</summary>
    private List<S7Block> PlanBlocks(IEnumerable<S7TagDef> tags)
    {
        var blocks = new List<S7Block>();
        foreach (var dbGroup in tags.GroupBy(t => t.DbNumber))
        {
            var ordered = dbGroup.OrderBy(t => t.StartByte).ToList();
            S7Block cur = null;

            foreach (var t in ordered)
            {
                int end = t.StartByte + t.Length - 1;
                // 间隙 ≤16 字节则合并（顺带读多点无所谓）
                if (cur != null && t.StartByte - cur.EndByte <= 16)
                {
                    cur.EndByte = Math.Max(cur.EndByte, end);
                    cur.Tags.Add(t);
                }
                else
                {
                    if (cur != null) blocks.Add(cur);
                    cur = new S7Block
                    {
                        DbNumber = t.DbNumber,
                        StartByte = t.StartByte,
                        EndByte = end,
                        Tags = new List<S7TagDef> { t }
                    };
                }
            }
            if (cur != null) blocks.Add(cur);
        }
        return blocks;
    }

    private static string BuildAddress(int db, int start, int len)
        => $"DB{db}.DBB{start} [{len}]";
}

public sealed class S7Block
{
    public int DbNumber { get; set; }
    public int StartByte { get; set; }
    public int EndByte { get; set; }
    public List<S7TagDef> Tags { get; set; }
    public int Length => EndByte - StartByte + 1;
    public int MaxLength { get; set; } = 200;
}
```

### 4.1 字节解析辅助

```csharp
public static class S7ValueParser
{
    /// <summary>注意 S7 是大端（Big-Endian）</summary>
    public static short ToInt16(byte[] buf, int offset) =>
        (short)((buf[offset] << 8) | buf[offset + 1]);

    public static int ToInt32(byte[] buf, int offset) =>
        (buf[offset] << 24) | (buf[offset + 1] << 16) | (buf[offset + 2] << 8) | buf[offset + 3];

    public static float ToReal(byte[] buf, int offset)
    {
        var b = new byte[] { buf[offset + 3], buf[offset + 2], buf[offset + 1], buf[offset] };
        return BitConverter.ToSingle(b, 0);
    }

    public static bool ToBool(byte buf, int bitIndex) => (buf & (1 << bitIndex)) != 0;

    /// <summary>S7 的 DT / DATE_AND_TIME 类型（8 字节 BCD）</summary>
    public static DateTime ToDateTime(byte[] buf, int offset)
    {
        int year = BcdToInt(buf[offset]);      // 0-99，表示 1990-2089
        int month = BcdToInt(buf[offset + 1]);
        int day = BcdToInt(buf[offset + 2]);
        int hour = BcdToInt(buf[offset + 3]);
        int minute = BcdToInt(buf[offset + 4]);
        int second = BcdToInt(buf[offset + 5]);
        int ms = BcdToInt(buf[offset + 6]) * 10 + BcdToInt(buf[offset + 7] >> 4);

        int fullYear = year >= 90 ? 1900 + year : 2000 + year;
        try
        {
            return new DateTime(fullYear, month, day, hour, minute, second, ms);
        }
        catch (ArgumentOutOfRangeException)
        {
            return DateTime.MinValue;   // BCD 数据未初始化时的常见情况
        }
    }

    /// <summary>S7 字符串（S7String）：前两字节是最大长度与当前长度</summary>
    public static string ToS7String(byte[] buf, int offset)
    {
        if (buf.Length < offset + 2) return string.Empty;
        int curLen = buf[offset + 1];
        if (curLen == 0) return string.Empty;
        int avail = Math.Min(curLen, buf.Length - offset - 2);
        return Encoding.ASCII.GetString(buf, offset + 2, avail).TrimEnd('\0', ' ');
    }

    private static int BcdToInt(byte b) => ((b >> 4) & 0x0F) * 10 + (b & 0x0F);
}
```

## 5. 连接保活与重连

```csharp
public sealed class S7ConnectionSupervisor : IDisposable
{
    private readonly Plc _plc;
    private readonly S7Config _cfg;
    private readonly ILogService _logger;
    private readonly ExponentialBackoff _backoff = new ExponentialBackoff(1000, 30000);
    private CancellationTokenSource _cts;
    private Task _supervisor;

    public void Start(CancellationToken ct)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _supervisor = Task.Run(() => RunAsync(_cts.Token));
    }

    private async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(5000, ct).ConfigureAwait(false);

                // 读一个已知的保活地址（如 DB1.DBX0.0 或 M0.0）
                bool alive = await Task.Run(() =>
                {
                    try { _plc.Read(_cfg.KeepAliveAddress); return true; }
                    catch { return false; }
                }, ct).ConfigureAwait(false);

                if (!alive) throw new IOException("S7 保活读取失败");

                _backoff.Reset();
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                _logger.Warn($"S7 连接异常，重连中：{ex.Message}");
                try
                {
                    await Task.Run(() => { try { _plc.Close(); } catch { } _plc.Open(); }, ct)
                              .ConfigureAwait(false);

                    if (_plc.IsConnected)
                        _logger.Info("S7 重连成功");
                    else
                        throw new IOException("重连后仍未连接");
                }
                catch (Exception rex)
                {
                    int delay = _backoff.NextDelayMs();
                    _logger.Warn($"S7 重连失败，{delay}ms 后重试：{rex.Message}");
                    try { await Task.Delay(delay, ct).ConfigureAwait(false); } catch { break; }
                }
            }
        }
    }

    public void Dispose()
    {
        try { _cts?.Cancel(); } catch { }
        try { _supervisor?.Wait(3000); } catch { }
        _cts?.Dispose();
    }
}
```

## 6. 地址格式速查

| 区域 | 地址格式 | 示例 | 说明 |
|---|---|---|---|
| 数据块 | `DB{n}.DBX{b}.{bit}` | `DB1.DBX0.0` | 位 |
| 数据块 | `DB{n}.DBB{b}` | `DB1.DBB10` | 字节 |
| 数据块 | `DB{n}.DBW{b}` | `DB1.DBW20` | 字（16 位，大端） |
| 数据块 | `DB{n}.DBD{b}` | `DB1.DBD30` | 双字（32 位） |
| 输入 | `I{b}.{bit}` / `IB/`IW/`ID` | `I0.0`, `IW64` | |
| 输出 | `Q{b}.{bit}` | `Q0.1` | |
| 位存储 | `M{b}.{bit}` | `M10.0` | |
| 定时器 | `T{n}` | `T1` | |
| 计数器 | `C{n}` | `C1` | |

**S7.Net 支持的地址字符串**（可直接传给 `Read`）：

```
"DB1.DBX0.0"        位
"DB1.DBB10"         字节
"DB1.DBW20"         字
"DB1.DBD30"         双字
"DB1.DBD40"         Real（需自行转 float）
"DB1.110"           S7 字符串
"MB10", "M10.0"     位存储
"IB0", "I0.0"       输入
"QB0", "Q0.0"       输出
"T1", "C1"          定时器/计数器
```

## 7. S7 踩坑清单

| 坑 | 现象 | 解法 |
|---|---|---|
| 未开 PUT/GET | 连接成功但读不到数据 | TIA 中勾选"允许 PUT/GET 通信访问" |
| DB 优化块访问未关 | 无固定地址，读取失败 | 取消"优化的块访问"，重新下载 |
| 机架/槽号错误 | 连接超时 | 300/400 用 R0/S2，1200/1500 用 R0/S1 |
| 单次读取超长 | 返回错误或截断 | 300/400 单块 ≤222 字节；1200/1500 ≤8192 |
| 多点逐点读取 | 慢（1 秒级） | 合并连续地址批量读 |
| 字节序搞反 | 数值异常 | S7 是大端，Real 需反转 4 字节 |
| 多线程同时读写 | 数据错乱或异常 | S7 连接非线程安全，必须加锁串行化 |
| 未释放连接 | PLC 连接资源耗尽 | 显式 Close，程序退出必调 |
| PLC 重启后连接假活 | 读到旧值 | 定时保活读 + 失败即重连 |
| 高频写入 | PLC 扫描周期被打乱 | 写操作限流，合并写入 |
| 读 Real 当 Int | 数值完全不对 | 明确数据类型，Real 走 ToReal |
| 时间类型未处理 BCD | 时间显示乱码 | 用 BCD 解析，注意年份 90 分界 |

## 8. S7 核对项

- [ ] PLC 具体型号与固件版本？
- [ ] IP 地址、机架号、槽号是否确认？
- [ ] PLC 是否已开启 PUT/GET 通信访问？
- [ ] 需访问的 DB 块是否已取消"优化的块访问"？
- [ ] DB 块号与每个标签的字节偏移、数据类型是否完整？
- [ ] 数据类型清单（Bool/Byte/Int/DInt/Word/DWord/Real/LReal/String/DT）？
- [ ] 单次最大读取长度限制（222 还是 8192）？
- [ ] 是否存在多客户端同时连接？PLC 最大连接数？
- [ ] 写操作的权限与范围限制？是否有安全联锁（如急停状态禁止写）？
- [ ] 扫描周期与上位机轮询周期的关系？轮询是否可能丢数据？
- [ ] 是否需要读取 PLC 诊断信息（模块状态、故障码）？
- [ ] 是否有安全 PLC（F-CPU）？F 变量不能直接读写。
- [ ] 断电重启后是否需要重新初始化某些寄存器（握手、使能）？
