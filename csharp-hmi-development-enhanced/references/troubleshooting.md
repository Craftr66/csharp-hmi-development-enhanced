# 上位机开发常见问题速查表

## 定位方法

遇到问题时，按以下顺序定位：
1. **先看日志** — 查看应用日志、Windows 事件查看器、设备通信日志
2. **最小复现** — 隔离问题场景，排除无关变量
3. **工具验证** — 用专业工具（串口调试助手、Wireshark、性能分析器）确认
4. **查本文档** — 对照下列模式速查

---

## 1. 性能问题

### 1.1 采样率上不去

**症状**：设计要求 100Hz 采样，实际只能达到 30Hz

**定位方法**：
```csharp
// 在关键路径打点
var sw = Stopwatch.StartNew();
// ... 你的采集代码
sw.Stop();
Logger.Debug($"采集耗时: {sw.ElapsedMilliseconds}ms");
```

**常见原因与解决**：

| 原因 | 现象 | 解决方案 |
|---|---|---|
| **串口读取阻塞** | 单次读取耗时 > 100ms | 改用异步读取 + 超时控制（见 `comm-serial.md`） |
| **数据库写入卡顿** | 每次写库 50ms+ | 批量写入（攒够 100 条再写）+ 异步队列 |
| **UI 刷新拖慢** | 主线程占用高 | UI 更新降频（100Hz 采样 → 20Hz 刷新） |
| **GC 暂停** | 采样时间不稳定，偶尔卡顿 | 预分配缓冲区，避免高频 new |
| **设备响应慢** | 设备本身延迟高 | 批量读取寄存器，减少单次请求数 |

**工具推荐**：
- **PerfView**：定位 CPU 热点、GC 暂停
- **dotTrace**：.NET 性能分析器
- **Stopwatch**：代码打点计时

---

### 1.2 内存持续增长

**症状**：程序运行几小时后内存从 200MB 涨到 2GB

**定位方法**：
```bash
# 使用 dotMemory 或 WinDbg 抓快照
# 对比两个时间点的快照，找增长的对象类型
```

**常见泄漏模式**：

| 模式 | 检查代码 | 修复 |
|---|---|---|
| **事件订阅未取消** | `device.DataReceived += OnData;` 但未 `-=` | 在 Dispose 中 `device.DataReceived -= OnData;` |
| **Stream 未释放** | `new FileStream()` 但未 `using` | 改用 `using (var fs = new FileStream(...))` |
| **定时器未停止** | `new System.Timers.Timer()` 未 `Stop()` | 在 Dispose 中 `timer.Stop(); timer.Dispose();` |
| **静态集合累积** | `static List<Data> _cache` 只增不删 | 定期清理或用 LRU 缓存 |
| **串口/网络缓冲区** | 发送队列堆积 | 检查发送是否成功，失败时丢弃旧数据 |

**工具推荐**：
- **dotMemory**（JetBrains）：可视化内存快照对比
- **WinDbg + SOS**：命令行诊断，`!dumpheap -stat` 查看对象统计

---

## 2. 通信问题

### 2.1 Modbus 读取失败

**症状**：`ReadHoldingRegisters` 返回异常码或超时

**检查清单**（按优先级）：

| 项目 | 检查方法 | 常见错误 |
|---|---|---|
| **从站地址** | 确认设备实际地址（如 `0x01`） | 用了默认值 `0x00` |
| **功能码** | 读保持寄存器用 `0x03`，线圈用 `0x01` | 功能码与寄存器类型不匹配 |
| **寄存器地址** | 设备手册地址是否从 0 或 1 开始 | 手册地址 40001 → 代码用 0 或 1（看协议） |
| **字节序** | 大端还是小端？ | 读到的数值颠倒（0x1234 变成 0x3412） |
| **波特率/校验位** | 串口参数与设备一致 | 9600,N,8,1 vs 9600,E,8,1 |
| **超时设置** | 至少给 500ms | 超时设置 100ms，设备来不及响应 |

**快速验证**：
- 用 **Modbus Poll** 或 **串口调试助手** 手动发报文，确认设备能响应
- 用 Wireshark（串口）或示波器验证物理层信号

---

### 2.2 TCP 连接频繁断开

**症状**：每隔几分钟就 `SocketException: Connection reset`

**原因排查**：

| 原因 | 现象 | 解决 |
|---|---|---|
| **没有心跳保活** | 空闲 > 2 分钟就断 | 实现心跳机制（见 `comm-tcp.md`） |
| **防火墙/路由器 NAT 超时** | 固定时长后断开 | 心跳间隔 < NAT 超时（一般 60s） |
| **设备主动断开** | 收到设备的 FIN 包 | 检查设备配置，可能有连接数限制 |
| **网络不稳定** | 随机断开 | 实现自动重连（见 `comm-tcp.md`） |
| **发送缓冲区满** | `Send()` 阻塞后超时 | 异步发送 + 超时控制 |

**重连策略推荐**：
```csharp
private async Task ReconnectLoop()
{
    int retryCount = 0;
    while (!_cts.IsCancellationRequested)
    {
        try
        {
            await ConnectAsync();
            retryCount = 0; // 成功后重置
            Logger.Info("TCP 连接成功");
            break;
        }
        catch (Exception ex)
        {
            retryCount++;
            int delay = Math.Min(retryCount * 2, 30); // 指数退避，最多 30 秒
            Logger.Warn($"连接失败，{delay}s 后重试: {ex.Message}");
            await Task.Delay(TimeSpan.FromSeconds(delay), _cts.Token);
        }
    }
}
```

---

## 3. UI 问题

### 3.1 界面卡顿/无响应

**症状**：点击按钮后界面冻结几秒，或拖动窗口时卡顿

**定位**：
- 用 Visual Studio **诊断工具** → CPU 使用率，看主线程占用
- 在可疑代码前后加 `Debug.WriteLine($"{DateTime.Now:HH:mm:ss.fff} - 开始执行")`

**常见原因**：

| 原因 | 代码特征 | 修复 |
|---|---|---|
| **UI 线程执行耗时操作** | `Button_Click` 中直接调用 `Thread.Sleep(3000)` 或同步 IO | 改用 `async/await`，耗时操作移到后台线程 |
| **频繁 Invoke** | 每收到一条数据就 `Invoke` 更新 UI | 降低刷新频率（100Hz → 20Hz），批量更新 |
| **大量控件重绘** | 一个 Panel 里有 1000 个 Label | 用虚拟化控件（如 `ListView` 虚拟模式） |
| **GDI 资源泄漏** | `new Pen()` 后未 `Dispose` | 用 `using` 或复用画笔对象 |

**反例与正例**：
```csharp
// ❌ 错误：UI 线程阻塞
private void btnRead_Click(object sender, EventArgs e)
{
    var data = SerialPort.ReadLine(); // 可能阻塞几秒
    txtResult.Text = data;
}

// ✅ 正确：异步执行
private async void btnRead_Click(object sender, EventArgs e)
{
    var data = await Task.Run(() => SerialPort.ReadLine());
    txtResult.Text = data;
}
```

---

### 3.2 曲线刷新闪烁

**症状**：实时曲线更新时整个控件闪烁

**解决方案**（按优先级）：
1. **启用双缓冲**：
   ```csharp
   SetStyle(ControlStyles.OptimizedDoubleBuffer | 
            ControlStyles.AllPaintingInWmPaint | 
            ControlStyles.UserPaint, true);
   ```
2. **只重绘变化区域**：
   ```csharp
   // 不要 Invalidate() 整个控件
   Rectangle dirtyRect = new Rectangle(lastX, 0, newX - lastX + 2, Height);
   Invalidate(dirtyRect);
   ```
3. **降低刷新率**：100Hz 采样 → 20Hz 界面刷新（人眼极限）
4. **用专业图表库**：如 **ScottPlot**、**LiveCharts**，性能优化更好

---

## 4. 架构问题

### 4.1 新设备接入困难

**症状**：每次加新设备都要改一堆地方，容易出错

**诊断**：
- 是否用了泛型抽象（`ITransport` → `IDeviceProtocol` → `IDeviceDriver`）？
- 新设备接入是否只需实现接口，不改其他代码？

**重构建议**：参考 `references/new-device-integration.md` 与 `references/generics-and-design.md`

---

### 4.2 多设备并发采集混乱

**症状**：10 个设备同时采集，数据张冠李戴或丢失

**常见错误**：
- 共享同一个串口对象（多线程冲突）
- 未做设备标识（数据回调时不知道是哪个设备的）
- 采样调度不合理（全部设备同时请求，设备响应超时）

**解决方案**：参考 `references/multi-device-orchestration.md`
- 每个设备独立的通信对象与线程
- 数据带设备 ID 标识
- 采用轮询调度器，错开设备采样时间

---

## 5. 现场部署问题

### 5.1 在现场运行报错，开发机正常

**检查清单**：

| 项目 | 开发机 | 现场 | 修复 |
|---|---|---|---|
| **.NET Framework 版本** | 4.8 | 可能只有 4.5 | 安装包内置 .NET Framework 安装程序 |
| **串口驱动** | 已装 | 可能缺失（USB 转串口） | 随安装包提供驱动 |
| **防火墙** | 关闭 | 开启 | 安装时引导用户添加白名单 |
| **文件路径** | `C:\Dev\Config.xml` | 不存在 | 用相对路径或 `AppDomain.CurrentDomain.BaseDirectory` |
| **权限不足** | 管理员 | 普通用户 | 安装到用户目录，或安装时提权 |

**自检脚本**：参考 `references/deployment-enhanced.md`，生成环境检测工具

---

### 5.2 远程调试困难

**工具包**（必备）：
- **日志上传功能**：一键打包所有日志 → 压缩 → 上传到指定服务器
- **参数导出**：导出当前配置文件（脱敏后）
- **版本信息收集**：软件版本、.NET 版本、操作系统、设备固件版本

**实现示例**：
```csharp
// 一键诊断
public void ExportDiagnostics()
{
    var zip = new ZipArchive(File.Create("Diagnostics.zip"), ZipArchiveMode.Create);
    zip.CreateEntryFromFile("logs/app.log", "app.log");
    zip.CreateEntryFromFile("config.xml", "config.xml");
    
    var info = new StringBuilder();
    info.AppendLine($"软件版本: {Assembly.GetExecutingAssembly().GetName().Version}");
    info.AppendLine($".NET 版本: {Environment.Version}");
    info.AppendLine($"操作系统: {Environment.OSVersion}");
    // ... 更多信息
    
    zip.CreateEntry("system_info.txt").Open().Write(Encoding.UTF8.GetBytes(info.ToString()));
    zip.Dispose();
    
    MessageBox.Show("诊断文件已生成：Diagnostics.zip");
}
```

---

## 6. 协议适配问题

### 6.1 设备固件升级后协议变了

**症状**：同一型号设备，新固件版本通信失败

**解决方案**（协议版本识别）：
1. **握手阶段查询固件版本**：
   ```csharp
   var version = await QueryFirmwareVersion();
   IDeviceProtocol protocol = version.StartsWith("2.") 
       ? new ProtocolV2() 
       : new ProtocolV1();
   ```
2. **维护版本迁移表**（在 `02-接口说明书.md` 中记录）：
   | 固件版本 | 协议变化 | 兼容性 |
   |---|---|---|
   | 1.0 - 1.5 | 寄存器地址 40001 开始 | 旧协议 |
   | 2.0+ | 寄存器地址 0 开始，新增心跳 | 新协议 |

3. **适配器模式**（参考 `references/new-device-integration.md`）

---

## 7. 工具推荐速查

| 场景 | 工具 | 用途 |
|---|---|---|
| **性能分析** | PerfView（免费）、dotTrace | CPU 热点、GC 暂停 |
| **内存泄漏** | dotMemory、WinDbg + SOS | 对象统计、快照对比 |
| **串口调试** | 串口调试助手、Modbus Poll | 手动发报文验证设备 |
| **网络抓包** | Wireshark、Fiddler | TCP/Modbus TCP 抓包分析 |
| **进程监控** | Process Explorer（Sysinternals）| 句柄泄漏、内存增长 |
| **长稳测试** | `scripts/long_run_monitor.py` | 自动监控 72 小时 |

---

## 使用建议

1. **先查本文档**，90% 的问题都有类似模式
2. **工具验证优先于猜测**，用专业工具定位根因
3. **记录新坑**，遇到本文档未覆盖的问题，解决后补充进来
4. **版本追溯**，在 `06-问题与风险台账.md` 中记录问题与解决方案
