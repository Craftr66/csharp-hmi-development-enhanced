# 新设备接入 SOP（标准操作流程）

## 适用场景

当遇到以下情况时，使用本 SOP：
- 设备/协议在 `references/comm-*.md` 中没有现成骨架代码
- 设备使用自定义私有协议
- 标准协议（如 Modbus）有特殊变体
- 需要为新设备类型建立接入模板

## 五步接入法

### 步骤 0 — 前置准备

**必须拿到的资料**（缺一不可）：
- [ ] 通信协议文档（报文格式、字节序、校验方式）
- [ ] 寄存器地址表 / 命令码表
- [ ] 设备手册（供电、接口类型、波特率）
- [ ] 示例代码或调试工具（如果有）

**可选但有帮助的资料**：
- 设备厂商提供的 SDK 或 Demo
- 其他平台的成功案例（Python、LabVIEW 等）
- 示波器或串口抓包记录

---

### 步骤 1 — 协议解析（手册 → 代码结构体）

#### 1.1 定义报文结构

**目标**：把协议文档翻译成 C# 结构体。

**示例**：某温控器查询温度命令

| 字段 | 字节数 | 说明 | 示例值 |
|---|---|---|---|
| 帧头 | 2 | 固定 `0xAA 0x55` | `AA 55` |
| 设备地址 | 1 | 从站地址 | `01` |
| 功能码 | 1 | `0x03` 读温度 | `03` |
| 数据长度 | 1 | 后续数据字节数 | `00`（查询无数据） |
| 校验和 | 1 | 所有字节异或 | `XOR` |

**对应 C# 代码**：
```csharp
public class TempControllerRequest
{
    public const byte HEADER_1 = 0xAA;
    public const byte HEADER_2 = 0x55;
    
    public byte DeviceAddress { get; set; }
    public byte FunctionCode { get; set; }
    public byte DataLength { get; set; }
    
    public byte[] ToBytes()
    {
        var buffer = new List<byte>
        {
            HEADER_1, HEADER_2,
            DeviceAddress,
            FunctionCode,
            DataLength
        };
        
        // 计算校验和
        byte checksum = 0;
        for (int i = 2; i < buffer.Count; i++) // 从地址开始
            checksum ^= buffer[i];
        buffer.Add(checksum);
        
        return buffer.ToArray();
    }
}
```

#### 1.2 定义响应结构

**响应报文**：

| 字段 | 字节数 | 说明 | 示例值 |
|---|---|---|---|
| 帧头 | 2 | 固定 `0xAA 0x55` | `AA 55` |
| 设备地址 | 1 | 回显请求地址 | `01` |
| 功能码 | 1 | 回显请求功能码 | `03` |
| 数据长度 | 1 | 温度数据 2 字节 | `02` |
| 温度高字节 | 1 | 温度值高 8 位 | `00` |
| 温度低字节 | 1 | 温度值低 8 位 | `C8` (200 = 20.0°C) |
| 校验和 | 1 | XOR | `XOR` |

**对应 C# 代码**：
```csharp
public class TempControllerResponse
{
    public byte DeviceAddress { get; set; }
    public byte FunctionCode { get; set; }
    public float Temperature { get; set; } // 单位：°C
    
    public static TempControllerResponse Parse(byte[] data)
    {
        if (data.Length < 7)
            throw new InvalidDataException("响应报文长度不足");
        
        if (data[0] != 0xAA || data[1] != 0x55)
            throw new InvalidDataException("帧头错误");
        
        // 校验和验证
        byte checksum = 0;
        for (int i = 2; i < data.Length - 1; i++)
            checksum ^= data[i];
        if (checksum != data[data.Length - 1])
            throw new InvalidDataException("校验和错误");
        
        int tempRaw = (data[5] << 8) | data[6]; // 大端字节序
        
        return new TempControllerResponse
        {
            DeviceAddress = data[2],
            FunctionCode = data[3],
            Temperature = tempRaw / 10.0f // 原始值 / 10 = 实际温度
        };
    }
}
```

---

### 步骤 2 — 最小验证（发一帧、收一帧）

**目标**：在独立的 Console 程序里，验证能和设备通信。

#### 2.1 创建最小测试程序

```csharp
using System;
using System.IO.Ports;
using System.Threading;

class MinimalTest
{
    static void Main(string[] args)
    {
        // 1. 打开串口
        var port = new SerialPort("COM3", 9600, Parity.None, 8, StopBits.One);
        port.Open();
        Console.WriteLine("串口已打开");
        
        // 2. 构造查询温度命令
        var request = new TempControllerRequest
        {
            DeviceAddress = 0x01,
            FunctionCode = 0x03,
            DataLength = 0x00
        };
        byte[] sendData = request.ToBytes();
        
        // 3. 发送
        Console.WriteLine($"发送: {BitConverter.ToString(sendData)}");
        port.Write(sendData, 0, sendData.Length);
        
        // 4. 接收
        Thread.Sleep(500); // 给设备响应时间
        int bytesAvailable = port.BytesToRead;
        if (bytesAvailable > 0)
        {
            byte[] recvData = new byte[bytesAvailable];
            port.Read(recvData, 0, bytesAvailable);
            Console.WriteLine($"接收: {BitConverter.ToString(recvData)}");
            
            // 5. 解析
            try
            {
                var response = TempControllerResponse.Parse(recvData);
                Console.WriteLine($"温度: {response.Temperature}°C");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"解析失败: {ex.Message}");
            }
        }
        else
        {
            Console.WriteLine("未收到响应");
        }
        
        port.Close();
    }
}
```

#### 2.2 验证清单

- [ ] 能打开串口（波特率、校验位、停止位正确）
- [ ] 能发送报文（用示波器或串口调试助手看到完整报文）
- [ ] 能收到响应（设备有返回数据）
- [ ] 能正确解析（温度值与实际一致，校验和通过）

**常见问题**：
| 现象 | 原因 | 解决 |
|---|---|---|
| 打开串口失败 | 端口被占用 | 关闭其他串口工具 |
| 发送后无响应 | 波特率不对 | 尝试其他波特率（9600/19200/38400） |
| 收到乱码 | 校验位或停止位不对 | 改为 Parity.Even 或 StopBits.Two |
| 校验和错误 | 字节序或校验算法错误 | 对照协议文档重新计算 |

---

### 步骤 3 — 泛型抽象映射（实现 `IDeviceProtocol`）

**目标**：把步骤 2 的代码封装成符合本技能架构的接口实现。

#### 3.1 定义设备协议接口

参考 `references/generics-and-design.md`，本技能使用三层抽象：

```
ITransport (传输层) → IDeviceProtocol (协议层) → IDeviceDriver (设备驱动层)
```

**温控器协议实现**：

```csharp
public class TempControllerProtocol : IDeviceProtocol
{
    private readonly ITransport _transport; // 串口、TCP 等
    private readonly byte _deviceAddress;
    
    public TempControllerProtocol(ITransport transport, byte deviceAddress)
    {
        _transport = transport;
        _deviceAddress = deviceAddress;
    }
    
    public async Task<float> ReadTemperatureAsync(CancellationToken ct)
    {
        // 1. 构造请求
        var request = new TempControllerRequest
        {
            DeviceAddress = _deviceAddress,
            FunctionCode = 0x03,
            DataLength = 0x00
        };
        
        // 2. 发送
        await _transport.SendAsync(request.ToBytes(), ct);
        
        // 3. 接收（带超时）
        byte[] response = await _transport.ReceiveAsync(7, TimeSpan.FromMilliseconds(500), ct);
        
        // 4. 解析
        var parsed = TempControllerResponse.Parse(response);
        return parsed.Temperature;
    }
    
    // ... 其他命令（设置温度、读湿度等）
}
```

#### 3.2 定义设备驱动（业务层）

```csharp
public class TempControllerDriver : IDeviceDriver
{
    private readonly TempControllerProtocol _protocol;
    private readonly Timer _samplingTimer;
    
    public event EventHandler<TemperatureData> DataReceived;
    
    public TempControllerDriver(ITransport transport, byte address)
    {
        _protocol = new TempControllerProtocol(transport, address);
        _samplingTimer = new Timer(OnSamplingTick, null, Timeout.Infinite, Timeout.Infinite);
    }
    
    public void StartSampling(int intervalMs)
    {
        _samplingTimer.Change(0, intervalMs);
    }
    
    public void StopSampling()
    {
        _samplingTimer.Change(Timeout.Infinite, Timeout.Infinite);
    }
    
    private async void OnSamplingTick(object state)
    {
        try
        {
            float temp = await _protocol.ReadTemperatureAsync(CancellationToken.None);
            DataReceived?.Invoke(this, new TemperatureData
            {
                Timestamp = DateTime.Now,
                Value = temp
            });
        }
        catch (Exception ex)
        {
            Logger.Error($"采样失败: {ex.Message}");
        }
    }
    
    public void Dispose()
    {
        _samplingTimer?.Dispose();
    }
}
```

---

### 步骤 4 — 测试用例编写

**目标**：为新设备写单元测试，覆盖正常与异常场景。

#### 4.1 正常流程测试

```csharp
[TestMethod]
public async Task TestReadTemperature_Success()
{
    // Arrange
    var mockTransport = new MockTransport();
    mockTransport.SetupResponse(new byte[] { 0xAA, 0x55, 0x01, 0x03, 0x02, 0x00, 0xC8, 0xXX }); // 20.0°C
    var protocol = new TempControllerProtocol(mockTransport, 0x01);
    
    // Act
    float temp = await protocol.ReadTemperatureAsync(CancellationToken.None);
    
    // Assert
    Assert.AreEqual(20.0f, temp, 0.1f);
}
```

#### 4.2 异常场景测试

```csharp
[TestMethod]
[ExpectedException(typeof(TimeoutException))]
public async Task TestReadTemperature_Timeout()
{
    var mockTransport = new MockTransport();
    mockTransport.SetupNoResponse(); // 设备无响应
    var protocol = new TempControllerProtocol(mockTransport, 0x01);
    
    await protocol.ReadTemperatureAsync(CancellationToken.None);
}

[TestMethod]
[ExpectedException(typeof(InvalidDataException))]
public async Task TestReadTemperature_ChecksumError()
{
    var mockTransport = new MockTransport();
    mockTransport.SetupResponse(new byte[] { 0xAA, 0x55, 0x01, 0x03, 0x02, 0x00, 0xC8, 0xFF }); // 校验和错误
    var protocol = new TempControllerProtocol(mockTransport, 0x01);
    
    await protocol.ReadTemperatureAsync(CancellationToken.None);
}
```

#### 4.3 压力测试

```csharp
[TestMethod]
public async Task TestContinuousSampling_1000Cycles()
{
    var driver = new TempControllerDriver(realTransport, 0x01);
    int successCount = 0;
    
    driver.DataReceived += (s, e) => successCount++;
    driver.StartSampling(100); // 100ms 采样一次
    
    await Task.Delay(100_000); // 运行 100 秒
    driver.StopSampling();
    
    Assert.IsTrue(successCount >= 900, $"成功率低于 90%: {successCount}/1000");
}
```

---

### 步骤 5 — 文档沉淀

**目标**：把新设备接入经验反哺回本技能，供下次复用。

#### 5.1 更新 `02-接口与通信协议说明书.md`

在项目文档中新增一节：

```markdown
## 4. 温控器通信协议（XX 品牌 YY 型号）

### 4.1 基本参数
- 通信方式：RS485
- 波特率：9600
- 数据位：8
- 校验位：无
- 停止位：1
- 设备地址：可配置（默认 0x01）

### 4.2 报文格式
| 帧头 | 地址 | 功能码 | 数据长度 | 数据 | 校验和 |
|---|---|---|---|---|---|
| AA 55 | 1B | 1B | 1B | 0-255B | 1B (XOR) |

### 4.3 功能码定义
| 功能码 | 功能 | 数据长度 |
|---|---|---|
| 0x03 | 读温度 | 0 |
| 0x04 | 读湿度 | 0 |
| 0x10 | 设置温度 | 2 (温度 * 10) |

### 4.4 已知问题
- 固件版本 < 2.0 时，校验和计算**不包含**帧头（与手册不符）
- 设备响应延迟约 200ms，超时建议设置 ≥ 500ms
- 连续发送间隔需 > 50ms，否则设备可能漏响应
```

#### 5.2 创建可复用模板（可选）

如果该类设备未来还会接入，可在 `assets/templates/` 创建模板：

```
assets/templates/temp-controller-template.cs
```

把 `TempControllerProtocol` 泛化为 `GenericXXXProtocol`，留出可配置参数（帧头、校验方式等）。

#### 5.3 补充到 `references/` （如果通用）

如果该协议有行业通用性（如某类仪表的标准协议），可新建：

```
references/comm-temp-controller-standard.md
```

参考 `comm-modbus.md` 的格式，写清楚：
- 协议规范来源
- 骨架代码
- 常见坑
- 厂商变体对照表

---

## 接入后维护

### 协议版本管理

如果设备固件升级导致协议变化，采用**适配器模式**：

```csharp
public interface ITempControllerProtocol
{
    Task<float> ReadTemperatureAsync(CancellationToken ct);
}

public class TempControllerProtocolV1 : ITempControllerProtocol
{
    // 旧协议实现
}

public class TempControllerProtocolV2 : ITempControllerProtocol
{
    // 新协议实现（帧头变了、新增心跳等）
}

public class TempControllerDriver
{
    private ITempControllerProtocol _protocol;
    
    public async Task ConnectAsync()
    {
        // 握手阶段查询固件版本
        string version = await QueryFirmwareVersion();
        
        _protocol = version.StartsWith("2.") 
            ? new TempControllerProtocolV2(_transport, _address)
            : new TempControllerProtocolV1(_transport, _address);
    }
}
```

### 版本迁移表

在 `02-接口说明书.md` 中维护：

| 固件版本 | 协议变化 | 兼容性 | 备注 |
|---|---|---|---|
| 1.0 - 1.5 | 帧头 AA 55，无心跳 | V1 协议 | 2020 年前出厂 |
| 2.0 - 2.3 | 帧头改为 BB 66，新增心跳 | V2 协议 | 2020 年后出厂 |
| 2.4+ | 新增固件升级命令 | V2 协议 | 需软件 >= 3.0 |

---

## 总结

新设备接入的**核心纪律**：
1. **先拿协议文档，不猜**
2. **先最小验证，再封装**
3. **用泛型抽象，保持架构一致性**
4. **写测试用例，覆盖异常**
5. **文档沉淀，供下次复用**

遇到问题时，参考 `references/troubleshooting.md` 的通信问题排查清单。
