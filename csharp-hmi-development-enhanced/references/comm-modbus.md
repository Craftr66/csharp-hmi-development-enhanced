# Modbus RTU / TCP 实现规范

## 1. 协议要点速查

### 1.1 功能码

| 功能码 | 名称 | 数据单位 | 说明 |
|---|---|---|---|
| 0x01 | Read Coils | 位 | 读线圈（可读写布尔） |
| 0x02 | Read Discrete Inputs | 位 | 读离散输入（只读布尔） |
| 0x03 | Read Holding Registers | 16 位 | **最常用**，读保持寄存器 |
| 0x04 | Read Input Registers | 16 位 | 读输入寄存器（只读） |
| 0x05 | Write Single Coil | 位 | 写单个线圈 |
| 0x06 | Write Single Register | 16 位 | 写单个寄存器 |
| 0x0F | Write Multiple Coils | 位 | 写多个线圈 |
| 0x10 | Write Multiple Registers | 16 位 | **最常用**，写多个寄存器 |

### 1.2 关键地址换算（**最容易出错的点**）

设备手册常用 1-based 表示法，协议帧用 0-based：

| 手册地址 | 功能码 | 协议帧地址 | 说明 |
|---|---|---|---|
| 00001–09999 | 0x01 | 0–9998 | 线圈，减 1 |
| 10001–19999 | 0x02 | 0–9998 | 离散输入，减 10001 |
| 30001–39999 | 0x04 | 0–9998 | 输入寄存器，减 30001 |
| 40001–49999 | 0x03 | 0–9998 | 保持寄存器，减 40001 |

**上位机必须内置地址转换层**，配置里用哪套表示法要写清楚：

```csharp
public static class ModbusAddress
{
    /// <summary>把设备手册的 1-based 地址转换成协议帧 0-based 地址</summary>
    public static ushort ManualToWire(string manualAddress, out byte functionCode)
    {
        // 支持 "40001"、"4x0001"、"40001.0"（位偏移）三种写法
        var clean = manualAddress.Split('.')[0].Replace("x", "").Replace("X", "");
        if (clean.Length < 5)
        {
            functionCode = 0x03;
            return ushort.Parse(clean);   // 已按 0-based 配置
        }

        int prefix = clean[0] - '0';
        int offset = int.Parse(clean.Substring(1));
        switch (prefix)
        {
            case 0: functionCode = 0x01; return (ushort)(offset - 1);
            case 1: functionCode = 0x02; return (ushort)(offset - 1);
            case 3: functionCode = 0x04; return (ushort)(offset - 1);
            case 4: functionCode = 0x03; return (ushort)(offset - 1);
            default: throw new ArgumentException($"无法识别的 Modbus 地址：{manualAddress}");
        }
    }
}
```

### 1.3 字节序（**第二大坑**）

32 位及以上数据存在 4 种寄存器内字节序 + 2 种寄存器间顺序，共 8 种组合：

| 名称 | 说明 |
|---|---|
| ABCD | 大端（默认，最标准） |
| CDAB | 字交换（西门子/部分仪表常用） |
| BADC | 字节交换 |
| DCBA | 全交换（小端） |

```csharp
public enum ModbusEndian { ABCD, CDAB, BADC, DCBA }

public static class ModbusConvert
{
    public static int ToInt32(ushort[] regs, int index, ModbusEndian endian)
    {
        byte[] b = new byte[4];
        switch (endian)
        {
            case ModbusEndian.ABCD:     // 高字在前，字内大端
                b[0] = (byte)(regs[index] >> 8); b[1] = (byte)regs[index];
                b[2] = (byte)(regs[index + 1] >> 8); b[3] = (byte)regs[index + 1];
                break;
            case ModbusEndian.CDAB:     // 字交换
                b[0] = (byte)(regs[index + 1] >> 8); b[1] = (byte)regs[index + 1];
                b[2] = (byte)(regs[index] >> 8); b[3] = (byte)regs[index];
                break;
            case ModbusEndian.BADC:     // 字节交换
                b[0] = (byte)regs[index]; b[1] = (byte)(regs[index] >> 8);
                b[2] = (byte)regs[index + 1]; b[3] = (byte)(regs[index + 1] >> 8);
                break;
            case ModbusEndian.DCBA:
                b[0] = (byte)regs[index + 1]; b[1] = (byte)(regs[index + 1] >> 8);
                b[2] = (byte)regs[index]; b[3] = (byte)(regs[index] >> 8);
                break;
        }
        return BitConverter.ToInt32(b, 0);
    }

    public static float ToFloat32(ushort[] regs, int index, ModbusEndian endian)
        => BitConverter.ToSingle(BitConverter.GetBytes(ToInt32(regs, index, endian)), 0);

    public static ushort[] FromInt32(int value, ModbusEndian endian)
    {
        var b = BitConverter.GetBytes(value);
        ushort hi = (ushort)((b[0] << 8) | b[1]);
        ushort lo = (ushort)((b[2] << 8) | b[3]);
        return endian == ModbusEndian.ABCD ? new[] { hi, lo } : new[] { lo, hi };
    }
}
```

> ⚠️ **字节序不能靠猜**。必须拿到设备手册明确说明，或用已知数值（如写 1.0 = 0x3F800000）反推验证。这是上位机联调阶段最高频的问题。

## 2. 完整实现：Modbus RTU

```csharp
using System;
using System.Threading;
using System.Threading.Tasks;

public sealed class ModbusRtuProtocol : IDeviceProtocol
{
    private readonly byte _slaveId;
    private readonly ModbusEndian _endian;
    private readonly ILogService _logger;

    public string Name => "ModbusRTU";

    public ModbusRtuProtocol(byte slaveId, ModbusEndian endian, ILogService logger)
    {
        _slaveId = slaveId;
        _endian = endian;
        _logger = logger;
    }

    // ---------- 建帧 ----------

    public byte[] BuildReadCommand(ProtocolReadRequest req)
    {
        // | slave | func | startHi | startLo | qtyHi | qtyLo | crcLo | crcHi |
        var frame = new byte[8];
        frame[0] = _slaveId;
        frame[1] = req.FunctionCode;
        frame[2] = (byte)(req.StartAddress >> 8);
        frame[3] = (byte)req.StartAddress;
        frame[4] = (byte)(req.Quantity >> 8);
        frame[5] = (byte)req.Quantity;
        AppendCrc(frame, 6);
        return frame;
    }

    public byte[] BuildWriteCommand(ProtocolWriteRequest req)
    {
        if (req.Values.Length == 1 && req.FunctionCode == 0x06)
        {
            var f = new byte[8];
            f[0] = _slaveId; f[1] = 0x06;
            f[2] = (byte)(req.StartAddress >> 8); f[3] = (byte)req.StartAddress;
            f[4] = (byte)(req.Values[0] >> 8); f[5] = (byte)req.Values[0];
            AppendCrc(f, 6);
            return f;
        }

        // 0x10 写多寄存器
        int qty = req.Values.Length;
        var frame = new byte[9 + qty * 2];
        frame[0] = _slaveId;
        frame[1] = 0x10;
        frame[2] = (byte)(req.StartAddress >> 8); frame[3] = (byte)req.StartAddress;
        frame[4] = (byte)(qty >> 8); frame[5] = (byte)qty;
        frame[6] = (byte)(qty * 2);
        for (int i = 0; i < qty; i++)
        {
            frame[7 + i * 2] = (byte)(req.Values[i] >> 8);
            frame[8 + i * 2] = (byte)req.Values[i];
        }
        AppendCrc(frame, frame.Length - 2);
        return frame;
    }

    // ---------- 解析 ----------

    public bool TryMatchResponse(byte[] buffer, out int frameLength)
    {
        frameLength = 0;
        if (buffer.Length < 5) return false;

        // 异常响应：slave | func|0x80 | exceptionCode | crcLo | crcHi
        bool isException = (buffer[1] & 0x80) != 0;
        if (isException)
        {
            if (buffer.Length < 5) return false;
            frameLength = 5;
            return true;
        }

        byte func = buffer[1];
        if (func == 0x03 || func == 0x04 || func == 0x01 || func == 0x02)
        {
            // 响应：slave | func | byteCount | data... | crcLo | crcHi
            int byteCount = buffer[2];
            frameLength = 3 + byteCount + 2;
            return buffer.Length >= frameLength;
        }

        if (func == 0x06 || func == 0x10 || func == 0x05 || func == 0x0F)
        {
            frameLength = 8;
            return buffer.Length >= 8;
        }

        return false;
    }

    /// <summary>RTU 响应的期望长度（用于 ReceiveAsync 精确读取）</summary>
    public static int ExpectedResponseLength(byte functionCode, int quantity) =>
        functionCode == 0x03 || functionCode == 0x04 || functionCode == 0x01
            ? 5 + quantity * 2
            : 8;

    public ProtocolResponse Parse(byte[] rawFrame)
    {
        if (rawFrame.Length < 5) throw new ProtocolException("Modbus 帧长度不足");

        if (!VerifyCrc(rawFrame, rawFrame.Length - 2))
            throw new CrcException($"Modbus CRC 校验失败，帧：{BitConverter.ToString(rawFrame)}");

        if ((rawFrame[1] & 0x80) != 0)
        {
            byte code = rawFrame[2];
            throw new ModbusExceptionException(_slaveId, rawFrame[1] & 0x7F, code, DescribeException(code));
        }

        byte func = rawFrame[1];
        if (func == 0x03 || func == 0x04)
        {
            int byteCount = rawFrame[2];
            int qty = byteCount / 2;
            var regs = new ushort[qty];
            for (int i = 0; i < qty; i++)
                regs[i] = (ushort)((rawFrame[3 + i * 2] << 8) | rawFrame[4 + i * 2]);
            return new ProtocolResponse { Registers = regs };
        }

        if (func == 0x01 || func == 0x02)
        {
            int byteCount = rawFrame[2];
            var bits = new bool[byteCount * 8];
            for (int i = 0; i < byteCount; i++)
                for (int b = 0; b < 8; b++)
                    bits[i * 8 + b] = (rawFrame[3 + i] & (1 << b)) != 0;
            return new ProtocolResponse { Bits = bits };
        }

        if (func == 0x06 || func == 0x10)
            return new ProtocolResponse { EchoAddress = (ushort)((rawFrame[2] << 8) | rawFrame[3]) };

        return new ProtocolResponse();
    }

    private static string DescribeException(byte code) => code switch
    {
        0x01 => "非法功能码",
        0x02 => "非法数据地址",
        0x03 => "非法数据值",
        0x04 => "从站设备故障",
        0x05 => "确认（处理中，需轮询后续）",
        0x06 => "从站设备忙",
        0x08 => "存储奇偶校验错误",
        0x0A => "网关路径不可用",
        0x0B => "网关目标设备无响应",
        _ => $"未知异常码 0x{code:X2}"
    };

    // ---------- CRC ----------

    /// <summary>Modbus CRC16（多项式 0xA001，初值 0xFFFF，低字节在前）</summary>
    public static ushort Crc16(byte[] data, int offset, int length)
    {
        ushort crc = 0xFFFF;
        for (int i = offset; i < offset + length; i++)
        {
            crc ^= data[i];
            for (int b = 0; b < 8; b++)
                crc = (crc & 1) != 0 ? (ushort)((crc >> 1) ^ 0xA001) : (ushort)(crc >> 1);
        }
        return crc;
    }

    private static void AppendCrc(byte[] frame, int crcPos)
    {
        ushort crc = Crc16(frame, 0, crcPos);
        frame[crcPos] = (byte)(crc & 0xFF);        // 低字节在前
        frame[crcPos + 1] = (byte)(crc >> 8);
    }

    public static bool VerifyCrc(byte[] frame, int crcPos)
    {
        if (frame.Length < crcPos + 2) return false;
        ushort expected = (ushort)(frame[crcPos] | (frame[crcPos + 1] << 8));
        return Crc16(frame, 0, crcPos) == expected;
    }
}
```

## 3. 完整实现：Modbus TCP

```csharp
public sealed class ModbusTcpProtocol : IDeviceProtocol
{
    private readonly byte _unitId;
    private readonly ILogService _logger;
    private ushort _transactionId;

    public string Name => "ModbusTCP";

    // MBAP 头：transactionId(2) | protocolId(2) | length(2) | unitId(1) = 7 字节
    private const int MbapHeaderLength = 7;

    public byte[] BuildReadCommand(ProtocolReadRequest req)
    {
        // PDU: func(1) | start(2) | qty(2) = 5 字节
        var frame = new byte[MbapHeaderLength + 5];
        ushort tid = unchecked(++_transactionId);

        frame[0] = (byte)(tid >> 8);  frame[1] = (byte)tid;
        frame[2] = 0x00; frame[3] = 0x00;                   // protocol id = 0
        frame[4] = 0x00; frame[5] = 0x05;                   // length = unitId + PDU = 6? 注意：length 不含自身
        // 修正：length 字段 = 后续字节数 = unitId(1) + PDU(5) = 6
        frame[4] = 0x00; frame[5] = 0x06;
        frame[6] = _unitId;
        frame[7] = req.FunctionCode;
        frame[8] = (byte)(req.StartAddress >> 8);  frame[9] = (byte)req.StartAddress;
        frame[10] = (byte)(req.Quantity >> 8);     frame[11] = (byte)req.Quantity;
        return frame;
    }

    public byte[] BuildWriteCommand(ProtocolWriteRequest req)
    {
        int qty = req.Values.Length;
        int pduLen = 6 + qty * 2;                            // func + addr + qty + byteCount + data
        var frame = new byte[MbapHeaderLength + pduLen];
        ushort tid = unchecked(++_transactionId);

        frame[0] = (byte)(tid >> 8); frame[1] = (byte)tid;
        frame[2] = 0; frame[3] = 0;
        int length = pduLen + 1;
        frame[4] = (byte)(length >> 8); frame[5] = (byte)length;
        frame[6] = _unitId;
        frame[7] = 0x10;
        frame[8] = (byte)(req.StartAddress >> 8); frame[9] = (byte)req.StartAddress;
        frame[10] = (byte)(qty >> 8); frame[11] = (byte)qty;
        frame[12] = (byte)(qty * 2);
        for (int i = 0; i < qty; i++)
        {
            frame[13 + i * 2] = (byte)(req.Values[i] >> 8);
            frame[14 + i * 2] = (byte)req.Values[i];
        }
        return frame;
    }

    public bool TryMatchResponse(byte[] buffer, out int frameLength)
    {
        frameLength = 0;
        if (buffer.Length < MbapHeaderLength) return false;

        int length = (buffer[4] << 8) | buffer[5];           // 后续字节数
        frameLength = 6 + length;
        return buffer.Length >= frameLength;
    }

    public ProtocolResponse Parse(byte[] rawFrame)
    {
        if (rawFrame.Length < 9) throw new ProtocolException("Modbus TCP 帧长度不足");

        // ⚠️ Modbus TCP 无 CRC（以太网已保证完整），不要做 CRC 校验
        byte unitId = rawFrame[6];
        byte func = rawFrame[7];

        if ((func & 0x80) != 0)
        {
            byte code = rawFrame[8];
            throw new ModbusExceptionException(unitId, func & 0x7F, code, "见 RTU 异常码说明");
        }

        if (func == 0x03 || func == 0x04)
        {
            int byteCount = rawFrame[8];
            int qty = byteCount / 2;
            var regs = new ushort[qty];
            for (int i = 0; i < qty; i++)
                regs[i] = (ushort)((rawFrame[9 + i * 2] << 8) | rawFrame[10 + i * 2]);
            return new ProtocolResponse { Registers = regs };
        }

        if (func == 0x06 || func == 0x10)
            return new ProtocolResponse();

        return new ProtocolResponse();
    }
}
```

## 4. 批量读取优化（性能关键）

**核心原则：把散点地址合并成连续块读取，一次通信拿回多个值。**

```csharp
public sealed class ModbusPollPlanner
{
    private readonly int _maxRegistersPerRequest;   // 通常 125（0x03 上限）
    private readonly int _maxGapRegisters;          // 允许的地址间隙，超过则分块

    public ModbusPollPlanner(int maxRegistersPerRequest = 125, int maxGapRegisters = 8)
    {
        _maxRegistersPerRequest = Math.Min(maxRegistersPerRequest, 125);
        _maxGapRegisters = maxGapRegisters;
    }

    /// <summary>把离散标签规划成最少的连续读取块</summary>
    public List<PollBlock> Plan(IEnumerable<TagDefinition> tags)
    {
        var ordered = tags.OrderBy(t => t.WireAddress).ToList();
        var blocks = new List<PollBlock>();
        if (ordered.Count == 0) return blocks;

        var current = new PollBlock
        {
            Start = ordered[0].WireAddress,
            End = ordered[0].WireAddress + ordered[0].RegisterCount - 1,
            Tags = new List<TagDefinition> { ordered[0] }
        };

        for (int i = 1; i < ordered.Count; i++)
        {
            var t = ordered[i];
            int tagEnd = t.WireAddress + t.RegisterCount - 1;
            int gap = t.WireAddress - current.End - 1;
            int newLength = tagEnd - current.Start + 1;

            if (gap <= _maxGapRegisters && newLength <= _maxRegistersPerRequest)
            {
                current.End = Math.Max(current.End, tagEnd);
                current.Tags.Add(t);
            }
            else
            {
                blocks.Add(current);
                current = new PollBlock
                {
                    Start = t.WireAddress,
                    End = tagEnd,
                    Tags = new List<TagDefinition> { t }
                };
            }
        }
        blocks.Add(current);
        return blocks;
    }
}

public sealed class PollBlock
{
    public ushort Start { get; set; }
    public ushort End { get; set; }
    public List<TagDefinition> Tags { get; set; }
    public int Quantity => End - Start + 1;
}
```

**优化效果示例**：100 个散点标签

- 不合并：100 次请求 × 30ms = 3000ms
- 合并后（假设聚成 6 块）：6 次请求 × 30ms = 180ms
- **提速 16 倍**

## 5. 写入前的安全校验

```csharp
public static class ModbusWriteGuard
{
    /// <summary>写入前必须校验，避免误写导致设备损坏</summary>
    public static void Validate(ushort value, TagDefinition tag)
    {
        if (tag.Access != TagAccess.ReadWrite)
            throw new InvalidOperationException($"标签 {tag.Name} 为只读，禁止写入");

        if (tag.MinValue.HasValue && value < tag.MinValue.Value)
            throw new ArgumentOutOfRangeException(tag.Name, $"值 {value} 低于下限 {tag.MinValue}");

        if (tag.MaxValue.HasValue && value > tag.MaxValue.Value)
            throw new ArgumentOutOfRangeException(tag.Name, $"值 {value} 高于上限 {tag.MaxValue}");

        if (tag.WriteConfirmRequired && !tag.ConfirmNotified)
            throw new ConfirmRequiredException($"标签 {tag.Name} 写入需操作确认");
    }
}
```

**工业现实**：一个错误的写入可能导致产线停机或设备损坏。所有写操作必须具备：范围校验 + 权限校验 + 二次确认 + 操作日志（谁、何时、写什么、旧值新值）。

## 6. Modbus 踩坑清单

| 坑 | 现象 | 解法 |
|---|---|---|
| 地址 1-based / 0-based 混淆 | 读到相邻寄存器的值 | 内置地址转换层，配置中明确标注表示法 |
| 字节序错误 | 数值完全不对或量级差 | 用已知值反推，ABCD/CDAB 都要试 |
| 浮点数跨两个寄存器 | 高字低字颠倒 | 显式指定 32 位值的寄存器顺序 |
| 0x03 一次读超 125 寄存器 | 从站返回异常码 0x03 | 分块，且每块 ≤125 |
| RTU 响应长度算错 | 超时或读到拼接数据 | 用 `ExpectedResponseLength` 精确计算 |
| RS485 总线冲突 | 全部设备超时 | 总线级信号量串行化 |
| 未处理异常响应 | 解析崩溃 | 检查 `func & 0x80`，抛明确异常 |
| 从站忙(0x06) 直接失败 | 偶发通信失败 | 对 0x06/0x05 做有限重试 |
| Modbus TCP 误做 CRC 校验 | 一直 CRC 失败 | TCP 无 CRC，MBAP 只校验长度 |
| MBAP length 字段算错 | 对端不响应 | length = unitId(1) + PDU，**不含自身 6 字节头** |
| 事务 ID 不匹配响应 | 请求串扰 | 校验响应 transactionId 与请求一致 |
| 位与寄存器地址混用 | 写错对象 | 0x01/0x02 是位，0x03/0x04 是 16 位寄存器 |
| 忽略设备响应延迟 | 大设备读到旧值 | 写入后延时再读，或读回确认 |

## 7. Modbus 核对项

- [ ] 从站地址（Slave ID / Unit ID）是多少？是否有多个从站？
- [ ] 通信物理层：RTU（串口）还是 TCP？波特率/校验？
- [ ] 寄存器地址表是否完整？包含每个标签的功能码、地址、数据类型、量纲？
- [ ] 地址表示法是 1-based 还是 0-based？手册中的地址段前缀是什么？
- [ ] 32/64 位数据的字节序与寄存器顺序是否确认？是否用已知值验证过？
- [ ] 单次最大读寄存器数是多少（通常 125）？
- [ ] 是否有写入权限限制？哪些标签可写？
- [ ] 写操作的合法范围（上下限）是否定义？是否需二次确认？
- [ ] 从站支持哪些功能码？是否有不支持 0x10 只支持 0x06 的？
- [ ] 通信超时、重试次数、从站忙时的处理策略？
- [ ] 是否存在"写后需延时生效"的寄存器？
- [ ] 是否有心跳/看门狗寄存器需要定时喂？
- [ ] 采样周期与总请求耗时的匹配（周期必须 > 一轮轮询总时间）？
