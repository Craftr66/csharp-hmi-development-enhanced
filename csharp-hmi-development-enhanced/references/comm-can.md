# CAN / CANopen 通信实现规范

## 1. 硬件与驱动选型

| 硬件 | 上位机接口 | 库 |
|---|---|---|
| ZLG（周立功）USBCAN-I/II | DLL | `ControlCAN.dll`（官方，推荐国内项目） |
| 广成科技 GCAN | DLL | `ECanVci.dll` |
| PEAK PCAN-USB | DLL | `PCANBasic.dll` |
| Kvaser | DLL | `CANlib32.dll` |
| IXXAT | DLL | `VCI4` |
| SocketCAN（Linux） | Socket | 不适用 Windows |

**通用做法**：抽象 `ICanChannel` 接口，各厂商 DLL 做适配器。下面以 ZLG 的 `ControlCAN.dll` 和 PEAK 风格统一说明。

## 2. CAN 基础概念速查

| 概念 | 说明 | 上位机关注点 |
|---|---|---|
| 标准帧 / 扩展帧 | 11 位 / 29 位 ID | 必须与设备一致，否则收不到 |
| 波特率 | 125K / 250K / 500K / 1M | 全网必须一致 |
| 数据帧 / 远程帧 | 有无数据场 | 远程帧用于请求 |
| 终端电阻 | 总线两端各 120Ω | 缺失时表现为随机错误 |
| 报文 ID | 标识符 | CANopen 中 ID = 功能码 + 节点号 |
| 数据长度 | 经典 CAN 0-8 字节；CAN FD 0-64 | 注意设备是否支持 FD |

**CANopen 报文 ID 分配**（COB-ID = 功能码 << 7 | NodeId）：

| 功能 | COB-ID 基址 | 方向 |
|---|---|---|
| NMT | 0x000 | 主→从 |
| SYNC | 0x080 | 主→从 |
| EMCY | 0x080 + NodeId | 从→主 |
| TPDO1 | 0x180 + NodeId | 从→主 |
| RPDO1 | 0x200 + NodeId | 主→从 |
| TPDO2 | 0x280 + NodeId | |
| RPDO2 | 0x300 + NodeId | |
| SDO 请求 | 0x600 + NodeId | 主→从 |
| SDO 响应 | 0x580 + NodeId | 从→主 |
| 心跳 | 0x700 + NodeId | 从→主 |

## 3. 通道抽象与实现

```csharp
using System;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;

public interface ICanChannel : IDisposable
{
    bool IsOpen { get; }
    bool Open(int deviceIndex, int channelIndex, CanBaudRate baud, bool extendedFrame);
    void Close();
    bool Send(CanFrame frame);
    bool TryReceive(out CanFrame frame, int timeoutMs);
    event EventHandler<CanFrame> FrameReceived;
    event EventHandler<CanErrorEventArgs> ErrorOccurred;
    CanStatistics Statistics { get; }
}

public struct CanFrame
{
    public uint Id;                 // 11 位标准帧或 29 位扩展帧
    public bool IsExtended;
    public bool IsRemote;
    public byte Length;             // 0-8
    public byte[] Data;             // 长度 8
    public uint TimestampUs;        // 硬件时间戳，用于抖动分析

    public override string ToString() =>
        $"{(IsExtended ? "EXT" : "STD")} 0x{Id:X3} [{(IsRemote ? "RTR" : "DAT")}] " +
        $"{BitConverter.ToString(Data, 0, Length).Replace("-", " ")}";
}

public sealed class CanStatistics
{
    public long TxCount;
    public long RxCount;
    public long TxErrorCount;
    public long RxErrorCount;
    public long BusOffCount;
    public long OverrunCount;
    public int TxQueueDepth;

    public double BusLoadPercent;       // 总线负载率，超过 40% 需警惕
}
```

### 3.1 ZLG 适配器实现

```csharp
public sealed class ZlgCanChannel : ICanChannel
{
    // ---- P/Invoke 声明（ControlCAN.dll）----
    [StructLayout(LayoutKind.Sequential)]
    private struct VCI_INIT_CONFIG
    {
        public uint AccCode;
        public uint AccMask;
        public uint Reserved;
        public byte Filter;
        public byte Timing0;
        public byte Timing1;
        public byte Mode;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct VCI_CAN_OBJ
    {
        public uint ID;
        public uint TimeStamp;
        public byte TimeFlag;
        public byte SendType;
        public byte RemoteFlag;
        public byte ExternFlag;
        public byte DataLen;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 8)]
        public byte[] Data;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 3)]
        public byte[] Reserved;
    }

    [DllImport("ControlCAN.dll", CallingConvention = CallingConvention.StdCall)]
    private static extern uint VCI_OpenDevice(uint devType, uint devIndex, uint reserved);

    [DllImport("ControlCAN.dll")]
    private static extern uint VCI_CloseDevice(uint devType, uint devIndex);

    [DllImport("ControlCAN.dll")]
    private static extern uint VCI_InitCAN(uint devType, uint devIndex, uint canIndex,
                                           ref VCI_INIT_CONFIG config);

    [DllImport("ControlCAN.dll")]
    private static extern uint VCI_StartCAN(uint devType, uint devIndex, uint canIndex);

    [DllImport("ControlCAN.dll")]
    private static extern uint VCI_Transmit(uint devType, uint devIndex, uint canIndex,
                                            VCI_CAN_OBJ[] objs, uint len);

    [DllImport("ControlCAN.dll")]
    private static extern uint VCI_Receive(uint devType, uint devIndex, uint canIndex,
                                           [Out] VCI_CAN_OBJ[] objs, uint len, int waitTime);

    [DllImport("ControlCAN.dll")]
    private static extern uint VCI_ReadErrInfo(uint devType, uint devIndex, uint canIndex,
                                               ref VCI_ERR_INFO info);

    private const uint DEV_TYPE_USBCAN2 = 4;
    private const uint DEV_TYPE_USBCAN1 = 3;

    private uint _devType = DEV_TYPE_USBCAN2;
    private uint _devIndex;
    private uint _canIndex;
    private bool _opened;

    public bool IsOpen => _opened;
    public CanStatistics Statistics { get; } = new CanStatistics();
    public event EventHandler<CanFrame> FrameReceived;
    public event EventHandler<CanErrorEventArgs> ErrorOccurred;

    public bool Open(int deviceIndex, int channelIndex, CanBaudRate baud, bool extendedFrame)
    {
        _devIndex = (uint)deviceIndex;
        _canIndex = (uint)channelIndex;

        if (VCI_OpenDevice(_devType, _devIndex, 0) != 1)
            throw new IOException($"打开 CAN 设备失败（设备索引 {deviceIndex}），请检查驱动与 USB 连接");

        var cfg = new VCI_INIT_CONFIG
        {
            AccCode = 0x00000000,
            AccMask = 0xFFFFFFFF,       // 接收所有 ID（不过滤）
            Filter = 0,
            Mode = 0                    // 0 = 正常模式；1 = 只听模式
        };
        (cfg.Timing0, cfg.Timing1) = GetTimingRegisters(baud);

        if (VCI_InitCAN(_devType, _devIndex, _canIndex, ref cfg) != 1)
        {
            VCI_CloseDevice(_devType, _devIndex);
            throw new IOException("初始化 CAN 通道失败");
        }

        if (VCI_StartCAN(_devType, _devIndex, _canIndex) != 1)
        {
            VCI_CloseDevice(_devType, _devIndex);
            throw new IOException("启动 CAN 通道失败");
        }

        _opened = true;
        return true;
    }

    /// <summary>ZLG 波特率寄存器值（SJA1000 时序）</summary>
    private static (byte T0, byte T1) GetTimingRegisters(CanBaudRate baud) => baud switch
    {
        CanBaudRate.Bps1000K => (0x00, 0x14),
        CanBaudRate.Bps800K  => (0x00, 0x16),
        CanBaudRate.Bps500K  => (0x00, 0x1C),
        CanBaudRate.Bps250K  => (0x01, 0x1C),
        CanBaudRate.Bps125K  => (0x03, 0x1C),
        CanBaudRate.Bps100K  => (0x04, 0x1C),
        CanBaudRate.Bps50K   => (0x09, 0x1C),
        CanBaudRate.Bps20K   => (0x18, 0x1C),
        CanBaudRate.Bps10K   => (0x31, 0x1C),
        _ => throw new ArgumentException($"不支持的波特率：{baud}")
    };

    public bool Send(CanFrame frame)
    {
        if (!_opened) throw new InvalidOperationException("CAN 通道未打开");

        var obj = new VCI_CAN_OBJ
        {
            ID = frame.Id,
            SendType = 0,                                   // 正常发送
            RemoteFlag = (byte)(frame.IsRemote ? 1 : 0),
            ExternFlag = (byte)(frame.IsExtended ? 1 : 0),
            DataLen = frame.Length,
            Data = new byte[8],
            Reserved = new byte[3]
        };
        Array.Copy(frame.Data, obj.Data, Math.Min(frame.Length, 8));

        uint ret = VCI_Transmit(_devType, _devIndex, _canIndex, new[] { obj }, 1);
        if (ret != 1)
        {
            Interlocked.Increment(ref Statistics.TxErrorCount);
            _lastError = $"发送失败，返回 {ret}";
            return false;
        }
        Interlocked.Increment(ref Statistics.TxCount);
        return true;
    }

    private string _lastError;

    /// <summary>专用接收线程：CAN 接收必须高频轮询，不能有延迟</summary>
    public void StartReceiveLoop(int pollIntervalMs = 1)
    {
        var thread = new Thread(() =>
        {
            var objs = new VCI_CAN_OBJ[200];
            while (_opened)
            {
                try
                {
                    uint count = VCI_Receive(_devType, _devIndex, _canIndex, objs, 200, pollIntervalMs);

                    if (count == 0xFFFFFFFF)   // 错误
                    {
                        var err = new VCI_ERR_INFO();
                        VCI_ReadErrInfo(_devType, _devIndex, _canIndex, ref err);
                        HandleErrorInfo(err);
                        continue;
                    }

                    for (uint i = 0; i < count; i++)
                    {
                        var f = new CanFrame
                        {
                            Id = objs[i].ID,
                            IsExtended = objs[i].ExternFlag == 1,
                            IsRemote = objs[i].RemoteFlag == 1,
                            Length = objs[i].DataLen,
                            Data = objs[i].Data,
                            TimestampUs = objs[i].TimeStamp
                        };
                        Interlocked.Increment(ref Statistics.RxCount);
                        FrameReceived?.Invoke(this, f);
                    }
                }
                catch (Exception ex)
                {
                    _lastError = ex.Message;
                    Thread.Sleep(10);
                }
            }
        })
        {
            IsBackground = true,
            Name = "CAN-Receive",
            Priority = ThreadPriority.AboveNormal     // 接收需及时，提升优先级
        };
        thread.Start();
    }

    private void HandleErrorInfo(VCI_ERR_INFO err)
    {
        if (err.ErrCode == 0) return;

        Interlocked.Increment(ref Statistics.BusOffCount);
        // ErrCode: 1=总线错误(溢出) 2=被动错误 3=总线关闭
        ErrorOccurred?.Invoke(this, new CanErrorEventArgs(
            (CanErrorType)err.ErrCode,
            $"CAN 错误码 {err.ErrCode}，总线状态 {err.PassiveErrData}"));
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct VCI_ERR_INFO
    {
        public uint ErrCode;
        public byte PassiveErrData;
        public byte ArLostErrData;
        public byte ErrorCode;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 3)]
        public byte[] Reserved;
    }

    public bool TryReceive(out CanFrame frame, int timeoutMs)
    {
        var objs = new VCI_CAN_OBJ[1];
        uint count = VCI_Receive(_devType, _devIndex, _canIndex, objs, 1, timeoutMs);
        if (count == 1)
        {
            frame = new CanFrame
            {
                Id = objs[0].ID,
                IsExtended = objs[0].ExternFlag == 1,
                IsRemote = objs[0].RemoteFlag == 1,
                Length = objs[0].DataLen,
                Data = objs[0].Data
            };
            return true;
        }
        frame = default;
        return false;
    }

    public void Close()
    {
        if (!_opened) return;
        _opened = false;
        Thread.Sleep(20);                       // 等接收线程退出
        VCI_CloseDevice(_devType, _devIndex);
    }

    public void Dispose() => Close();
}
```

## 4. CANopen PDO 解析

PDO 是 CANopen 数据交互的**高效通道**（无协议开销，一帧最多 8 字节映射多个对象）。

```csharp
public sealed class CanopenPdoParser
{
    private readonly Dictionary<uint, PdoDefinition> _pdoMap;
    private readonly ILogService _logger;

    public CanopenPdoParser(IEnumerable<PdoDefinition> definitions, ILogService logger)
    {
        _pdoMap = definitions.ToDictionary(
            p => p.CobId,
            p => p);
        _logger = logger;
    }

    /// <summary>根据 PDO 定义解析一帧数据，返回映射值</summary>
    public IReadOnlyDictionary<string, object> Parse(CanFrame frame)
    {
        var result = new Dictionary<string, object>();
        if (!_pdoMap.TryGetValue(frame.Id, out var pdo))
        {
            _logger.Trace($"未定义的 PDO COB-ID 0x{frame.Id:X3}，忽略");
            return result;
        }

        foreach (var map in pdo.Mappings)
        {
            if (map.ByteOffset + map.ByteLength > frame.Length)
            {
                _logger.Warn($"PDO 0x{frame.Id:X3} 映射 {map.Name} 超出报文长度");
                continue;
            }

            object v;
            switch (map.DataType)
            {
                case CanopenDataType.Unsigned8:
                    v = frame.Data[map.ByteOffset];
                    break;
                case CanopenDataType.Signed8:
                    v = (sbyte)frame.Data[map.ByteOffset];
                    break;
                case CanopenDataType.Unsigned16:
                    v = (ushort)(frame.Data[map.ByteOffset] |
                                 (frame.Data[map.ByteOffset + 1] << 8));   // CANopen 小端
                    break;
                case CanopenDataType.Signed16:
                    v = (short)(frame.Data[map.ByteOffset] |
                                (frame.Data[map.ByteOffset + 1] << 8));
                    break;
                case CanopenDataType.Unsigned32:
                    v = (uint)(frame.Data[map.ByteOffset] |
                               (frame.Data[map.ByteOffset + 1] << 8) |
                               (frame.Data[map.ByteOffset + 2] << 16) |
                               (frame.Data[map.ByteOffset + 3] << 24));
                    break;
                case CanopenDataType.Signed32:
                    v = (int)(frame.Data[map.ByteOffset] |
                              (frame.Data[map.ByteOffset + 1] << 8) |
                              (frame.Data[map.ByteOffset + 2] << 16) |
                              (frame.Data[map.ByteOffset + 3] << 24));
                    break;
                case CanopenDataType.Real32:
                    v = BitConverter.ToSingle(frame.Data, map.ByteOffset);
                    break;
                default:
                    continue;
            }

            result[map.Name] = v;
        }
        return result;
    }
}

public sealed class PdoDefinition
{
    public uint CobId { get; set; }
    public string Name { get; set; }
    public bool IsTpdo { get; set; }        // TPDO = 从站→主站；RPDO = 主站→从站
    public List<PdoMapping> Mappings { get; set; } = new List<PdoMapping>();
}

public sealed class PdoMapping
{
    public string Name { get; set; }
    public int ByteOffset { get; set; }
    public int ByteLength { get; set; }
    public CanopenDataType DataType { get; set; }
    public double Scale { get; set; } = 1.0;
    public string Unit { get; set; }
}

public enum CanopenDataType { Unsigned8, Signed8, Unsigned16, Signed16, Unsigned32, Signed32, Real32 }
```

## 5. SDO 读写（配置参数）

```csharp
public sealed class CanopenSdoClient
{
    private readonly ICanChannel _channel;
    private readonly ILogService _logger;
    private readonly object _sdoLock = new object();

    /// <summary>SDO 上传（读对象字典）</summary>
    public async Task<byte[]> UploadAsync(byte nodeId, ushort index, byte subIndex,
        int timeoutMs = 1000, CancellationToken ct = default)
    {
        lock (_sdoLock)   // SDO 是请求-响应，必须独占
        {
            uint cobId = 0x600u + nodeId;
            var req = new byte[8];
            req[0] = 0x40;                               // CCS=2 (upload), 无数据
            req[1] = (byte)(index & 0xFF);
            req[2] = (byte)(index >> 8);
            req[3] = subIndex;

            if (!_channel.Send(new CanFrame { Id = cobId, Length = 8, Data = req }))
                throw new IOException("SDO 上传请求发送失败");

            var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            uint respId = 0x580u + nodeId;

            while (DateTime.UtcNow < deadline)
            {
                ct.ThrowIfCancellationRequested();
                if (!_channel.TryReceive(out var resp, 10)) continue;
                if (resp.Id != respId) continue;

                byte ccs = (byte)(resp.Data[0] >> 5);
                if ((resp.Data[0] & 0x80) != 0)          // 异常响应
                {
                    uint abortCode = BitConverter.ToUInt32(resp.Data, 4);
                    throw new ProtocolException(
                        $"SDO 上传被中止：0x{abortCode:X8}（{DescribeAbort(abortCode)}）");
                }

                // 解析响应：查 index/subIndex 是否匹配
                ushort respIndex = (ushort)(resp.Data[1] | (resp.Data[2] << 8));
                if (respIndex != index || resp.Data[3] != subIndex) continue;

                bool expedited = (resp.Data[0] & 0x02) != 0;
                if (expedited)
                {
                    bool sizeIndicated = (resp.Data[0] & 0x01) != 0;
                    int len = sizeIndicated ? 4 - ((resp.Data[0] >> 2) & 0x03) : 4;
                    var data = new byte[len];
                    Array.Copy(resp.Data, 4, data, 0, len);
                    return data;
                }

                throw new ProtocolException("分段 SDO 上传暂未实现，请按需扩展");
            }
            throw new TimeoutException($"SDO 上传超时（节点 {nodeId}，0x{index:X4}:{subIndex}）");
        }
    }

    /// <summary>SDO 下载（写对象字典）</summary>
    public bool DownloadAsync(byte nodeId, ushort index, byte subIndex, byte[] data,
        int timeoutMs = 1000)
    {
        if (data.Length > 4)
            throw new NotSupportedException("仅支持加速 SDO（≤4 字节）");

        lock (_sdoLock)
        {
            uint cobId = 0x600u + nodeId;
            var req = new byte[8];
            // CCS=1 (download), expedited=1, sizeIndicated=1, n = 4 - length
            req[0] = (byte)(0x23 | ((4 - data.Length) << 2));
            req[1] = (byte)(index & 0xFF);
            req[2] = (byte)(index >> 8);
            req[3] = subIndex;
            Array.Copy(data, 0, req, 4, data.Length);

            if (!_channel.Send(new CanFrame { Id = cobId, Length = 8, Data = req }))
                return false;

            var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
            uint respId = 0x580u + nodeId;

            while (DateTime.UtcNow < deadline)
            {
                if (!_channel.TryReceive(out var resp, 10)) continue;
                if (resp.Id != respId) continue;

                if ((resp.Data[0] & 0x80) != 0)
                {
                    uint abortCode = BitConverter.ToUInt32(resp.Data, 4);
                    _logger.Error($"SDO 下载被中止：0x{abortCode:X8}");
                    return false;
                }

                if (resp.Data[0] == 0x60) return true;      // 下载成功响应
            }
            _logger.Warn($"SDO 下载超时（节点 {nodeId}，0x{index:X4}:{subIndex}）");
            return false;
        }
    }

    /// <summary>常用中止码</summary>
    private static string DescribeAbort(uint code) => code switch
    {
        0x05030000 => "触发位未切换",
        0x05040000 => "SDO 协议超时",
        0x06010000 => "不支持对该对象的访问",
        0x06010001 => "试图读只写对象",
        0x06010002 => "试图写只读对象",
        0x06020000 => "对象不存在",
        0x06070010 => "数据类型与长度不匹配",
        0x06090011 => "子索引不存在",
        0x06090030 => "参数值超范围",
        0x08000000 => "通用错误",
        _ => "未知中止码"
    };
}
```

## 6. NMT 状态控制与心跳

```csharp
public sealed class CanopenNmtMaster
{
    private readonly ICanChannel _channel;
    private readonly ILogService _logger;
    private readonly Dictionary<byte, DateTime> _lastHeartbeat = new Dictionary<byte, DateTime>();
    private readonly object _sync = new object();

    public event EventHandler<NodeHeartbeatLostEventArgs> HeartbeatLost;

    /// <summary>发送 NMT 命令（COB-ID 固定 0x000）</summary>
    public bool SendNmtCommand(byte nodeId, NmtCommand cmd)
    {
        var data = new byte[] { (byte)cmd, nodeId };
        var frame = new CanFrame { Id = 0x000, Length = 2, Data = data };
        _logger.Info($"NMT 命令 {cmd} → 节点 {(nodeId == 0 ? "全部" : nodeId.ToString())}");
        return _channel.Send(frame);
    }

    /// <summary>处理心跳报文（COB-ID = 0x700 + NodeId）</summary>
    public void OnFrame(CanFrame frame)
    {
        if (frame.Id < 0x700 || frame.Id > 0x77F) return;
        byte nodeId = (byte)(frame.Id - 0x700);
        lock (_sync) { _lastHeartbeat[nodeId] = DateTime.UtcNow; }
    }

    /// <summary>看门狗：定时检查心跳超时</summary>
    public void CheckHeartbeats(IEnumerable<CanopenNodeConfig> nodes)
    {
        var now = DateTime.UtcNow;
        foreach (var n in nodes)
        {
            DateTime last;
            lock (_sync)
            {
                if (!_lastHeartbeat.TryGetValue(n.NodeId, out last)) continue;
            }

            double ms = (now - last).TotalMilliseconds;
            if (ms > n.HeartbeatTimeoutMs)
            {
                _logger.Error($"节点 {n.NodeId}（{n.Name}）心跳丢失，已 {ms:F0}ms 无报文");
                HeartbeatLost?.Invoke(this, new NodeHeartbeatLostEventArgs(n.NodeId, ms));
            }
        }
    }
}

public enum NmtCommand : byte
{
    StartRemoteNode = 0x01,
    StopRemoteNode = 0x02,
    EnterPreOperational = 0x80,
    ResetNode = 0x81,
    ResetCommunication = 0x82
}

public sealed class CanopenNodeConfig
{
    public byte NodeId { get; set; }
    public string Name { get; set; }
    public int HeartbeatTimeoutMs { get; set; } = 3000;
}
```

## 7. 总线负载监控

```csharp
public sealed class CanBusLoadMonitor
{
    private long _lastRx, _lastTx;
    private DateTime _lastSample = DateTime.UtcNow;
    private readonly CanBaudRate _baud;

    /// <summary>估算总线负载率。超过 50% 时通信延迟会显著上升。</summary>
    public double Sample(CanStatistics stats)
    {
        var now = DateTime.UtcNow;
        double sec = (now - _lastSample).TotalSeconds;
        if (sec < 0.5) return stats.BusLoadPercent;

        long rx = Interlocked.Read(ref stats.RxCount);
        long tx = Interlocked.Read(ref stats.TxCount);

        long frames = (rx - _lastRx) + (tx - _lastTx);
        _lastRx = rx; _lastTx = tx;
        _lastSample = now;

        // 每帧约 (44 + 8*8 + 位填充) ≈ 110-135 位
        double bits = frames * 130.0;
        double capacity = BaudToBps(_baud) * sec;

        stats.BusLoadPercent = capacity > 0 ? bits / capacity * 100.0 : 0;
        return stats.BusLoadPercent;
    }

    private static long BaudToBps(CanBaudRate b) => b switch
    {
        CanBaudRate.Bps1000K => 1_000_000,
        CanBaudRate.Bps800K  => 800_000,
        CanBaudRate.Bps500K  => 500_000,
        CanBaudRate.Bps250K  => 250_000,
        CanBaudRate.Bps125K  => 125_000,
        CanBaudRate.Bps100K  => 100_000,
        CanBaudRate.Bps50K   => 50_000,
        CanBaudRate.Bps20K   => 20_000,
        CanBaudRate.Bps10K   => 10_000,
        _ => 500_000
    };
}
```

## 8. CAN 踩坑清单

| 坑 | 现象 | 解法 |
|---|---|---|
| 终端电阻缺失 | 随机错误、丢帧、总线关闭 | 总线两端各 120Ω，用万用表测 60Ω |
| 波特率不一致 | 完全收不到报文或大量错误帧 | 全网统一，逐台核对 |
| 标准/扩展帧不匹配 | 收到的 ID 完全不对 | 核对设备用的是 11 位还是 29 位 |
| 接收用轮询但周期太长 | 缓冲区溢出丢帧 | 专用高优先级线程，1ms 级轮询 |
| 发送队列满未检测 | 静默丢帧 | 检查发送返回值与队列深度 |
| 字节序搞错 | 数值不对 | CANopen 是小端；自定义协议需查手册 |
| 总线负载过高 | 延迟抖动大 | 控制发送频率，负载 <40%；优化 PDO 映射合并 |
| 未监听总线错误 | 总线已关闭但软件不知 | 订阅错误事件，BusOff 后自动恢复 |
| 多线程直接调用 DLL | 崩溃或数据错乱 | 发送加锁，接收单一线程 |
| 未关闭设备就退出 | 下次打开失败 | 退出时 CloseDevice |
| 心跳超时未处理 | 从站掉线但界面无提示 | 实现心跳看门狗 + 告警 |
| PDO 映射与配置不符 | 解析出错误数值 | 读取 0x1600/0x1A00 对象确认实际映射 |

## 9. CAN / CANopen 核对项

- [ ] CAN 适配器品牌型号？驱动是否安装？DLL 位数（x86/x64）是否与程序一致？
- [ ] 波特率是多少？全网是否一致？
- [ ] 使用标准帧还是扩展帧？
- [ ] 总线有哪几个节点？每个节点 ID 是多少？
- [ ] 终端电阻是否已确认（总线两端 120Ω）？
- [ ] 是否使用 CANopen？PDO 映射（COB-ID、对象、偏移、类型）是否已确认？
- [ ] 心跳周期与超时阈值？节点丢失后的处理策略？
- [ ] 是否需要 SDO 配置参数？参数清单是否完整？
- [ ] 是否有报文需要按周期发送（如 SYNC、RPDO）？周期多少？
- [ ] 总线负载率预估多少？是否留有余量？
- [ ] 是否有 BusOff 自动恢复机制？
- [ ] 是否需要硬件时间戳用于抖动分析？
- [ ] 是否需要 CAN FD？经典 CAN 与 FD 设备是否混用（不可混用）？
