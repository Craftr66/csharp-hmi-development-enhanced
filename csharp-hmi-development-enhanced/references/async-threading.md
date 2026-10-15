# 异步多线程与泛型开发规范（.NET Framework 4.8）

## 第一部分：异步与多线程

### 1. 总原则

1. **UI 线程只做渲染**。任何 >50ms 的操作都不得在 UI 线程执行。
2. **优先 `async/await`，慎用裸 `Thread`**。裸线程仅在隔离性要求极高（如 CAN 高优先级收发）或需 STA 单元时使用。
3. **禁止 `.Result` / `.Wait()` 在 UI 线程使用**——必然死锁。参见第 6 节。
4. **所有长生命周期任务必须持有 `CancellationToken`**。
5. **共享状态必须用不可变数据或同步原语保护**，禁止"碰运气"式并发。

### 2. 线程模型分配（上位机典型）

| 线程/任务 | 归属 | 说明 |
|---|---|---|
| UI 线程 | WinForms 消息泵 | 只处理绘制、输入、`BeginInvoke` 回调 |
| 采集任务（每设备一个） | `Task` + `CancellationToken` | 周期性轮询或事件驱动接收 |
| 接收任务（长连接） | 独立 `Task` 循环 `ReadAsync` | TCP/串口持续收包 |
| 数据处理任务 | `Task` 或 `BlockingCollection` 消费者 | 解析、换算、滤波、判限 |
| 落库任务 | 单消费者 + 批量提交 | 避免高频 IO |
| UI 刷新定时器 | `System.Windows.Forms.Timer` | 只在 UI 线程，仅做重绘 |
| 看门狗任务 | 独立 `Task` | 监测各任务心跳 |

**关键：UI 刷新定时器用 `System.Windows.Forms.Timer`（UI 线程），采集定时用 `System.Threading.Timer` 或自循环 `Task.Delay`（后台线程）。两者绝不可混用。**

### 3. UI 线程封送

**Windows Forms 的黄金法则：只有创建控件的线程才能访问该控件。**

```csharp
// 推荐：扩展方法封装，统一入口
public static class ControlExtensions
{
    public static void SafeInvoke(this Control control, Action action)
    {
        if (control == null || control.IsDisposed || !control.IsHandleCreated) return;

        if (control.InvokeRequired)
            control.BeginInvoke(action);   // BeginInvoke 不阻塞后台线程
        else
            action();
    }

    public static void SafeInvoke<T>(this Control control, Action<T> action, T arg)
    {
        if (control == null || control.IsDisposed || !control.IsHandleCreated) return;
        if (control.InvokeRequired)
            control.BeginInvoke(action, arg);
        else
            action(arg);
    }
}
```

**禁用 `Invoke`（同步版）**：在后台线程调用 `Invoke` 会阻塞等待 UI 线程，若 UI 线程此刻正在等待该后台线程 → 死锁。统一用 `BeginInvoke`。

**高频更新的降采样策略**：采集 1kHz 但 UI 只显示 25Hz，不要在回调里直接刷新，而是写入共享缓冲，由 UI 定时器批量取出绘图。

```csharp
// 数据侧：只写缓冲，不碰 UI
private readonly RingBuffer<Sample> _uiBuffer = new RingBuffer<Sample>(4096);

// UI 侧：Timer 25Hz 批量刷新
private void uiTimer_Tick(object sender, EventArgs e)
{
    var batch = _uiBuffer.DrainUpTo(2000);
    if (batch.Length == 0) return;
    _chart.AppendBatch(batch);          // 一次性追加，减少重绘
    lblCount.Text = _totalCount.ToString();
}
```

### 4. CancellationToken 正确用法

```csharp
public sealed class AcquisitionService : IAcquisitionService
{
    private CancellationTokenSource _cts;
    private Task _worker;

    public void Start()
    {
        if (_worker != null && !_worker.IsCompleted) return;
        _cts = new CancellationTokenSource();
        _worker = Task.Run(() => RunAsync(_cts.Token));
    }

    public async Task StopAsync(TimeSpan timeout)
    {
        if (_cts == null) return;
        _cts.Cancel();

        var completed = await Task.WhenAny(_worker, Task.Delay(timeout)).ConfigureAwait(false);
        if (completed != _worker)
            _logger.Warn("采集任务未在 {0} 内退出，可能阻塞在设备读取", timeout);

        _cts.Dispose();
        _cts = null;
    }

    private async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await PollOnceAsync(ct).ConfigureAwait(false);
                await Task.Delay(_intervalMs, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                _logger.Error(ex, "采集轮询异常");
                await Task.Delay(500, ct).ConfigureAwait(false);   // 异常退避
            }
        }
    }
}
```

**要点**：

- `Task.Delay(ms, ct)` 而不是 `Thread.Sleep(ms)` —— 后者无法取消，退出要等一个完整周期。
- 捕获 `OperationCanceledException` 视为正常退出，不记 Error。
- `CancellationTokenSource` 用完必须 `Dispose`。
- 若需"取消后不复用"，置 `_cts = null` 防止重复 Cancel。

### 5. 并发数据结构

| 场景 | 使用 | 禁用 |
|---|---|---|
| 高频采集写入 / UI 批量读出 | 自实现 `RingBuffer<T>`（无锁单生产单消费） | `List<T>` + `lock`（GC 压力大） |
| 多生产者多消费者队列 | `BlockingCollection<T>` 或 `ConcurrentQueue<T>` | `Queue<T>` |
| 共享字典（配置缓存、设备状态） | `ConcurrentDictionary<K,V>` | `Dictionary<K,V>` |
| 计数器 | `Interlocked.Increment` | `counter++` |
| 简单标志位 | `volatile bool` / `Interlocked.Exchange` | 裸 `bool` |
| 复杂复合操作 | `lock`（锁粒度尽量小） | 大范围 lock 包住 IO |

**无锁环形缓冲参考实现**（单生产者单消费者，上位机最常用）：

```csharp
public sealed class RingBuffer<T>
{
    private readonly T[] _buffer;
    private readonly int _capacity;
    private int _head;      // 写入位置
    private int _tail;      // 读取位置
    private int _count;
    private readonly object _drainLock = new object();

    public RingBuffer(int capacity)
    {
        // capacity 取 2 的幂，用位运算取模
        _capacity = capacity;
        _buffer = new T[capacity];
    }

    public void Write(T item)
    {
        _buffer[_head] = item;
        _head = (_head + 1) & (_capacity - 1);

        if (Interlocked.Increment(ref _count) > _capacity)
        {
            // 溢出：覆盖最旧数据
            _tail = (_tail + 1) & (_capacity - 1);
            Interlocked.Decrement(ref _count);
        }
    }

    public T[] DrainUpTo(int max)
    {
        lock (_drainLock)   // 保证同一时刻只有一个消费者
        {
            int n = Math.Min(max, Volatile.Read(ref _count));
            if (n <= 0) return Array.Empty<T>();

            var result = new T[n];
            for (int i = 0; i < n; i++)
            {
                result[i] = _buffer[_tail];
                _tail = (_tail + 1) & (_capacity - 1);
            }
            Interlocked.Add(ref _count, -n);
            return result;
        }
    }
}
```

> 注意：`T[]` 若为引用类型，溢出覆盖不会释放旧对象引用，需在覆盖前显式 `_buffer[_tail] = default(T)`。数值类型无此问题。

### 6. 死锁与陷阱速查

| 陷阱 | 症状 | 正确做法 |
|---|---|---|
| UI 线程 `.Result` / `.Wait()` | 界面永久卡死 | 改 `async void` 事件处理器 + `await`，或 `Task.Run` 后回调 |
| `Invoke` 在后台线程 | 偶发死锁 | 一律 `BeginInvoke` |
| `Task.Run` 里更新控件 | 跨线程异常 | `SafeInvoke` 封装 |
| `async void` 用于非事件方法 | 异常丢失、无法等待 | 仅事件处理器可用 `async void`，其余返回 `Task` |
| `lock` 中 `await` | 编译期报错（好）或逻辑死锁 | 拆分临界区，先取数据再出锁 |
| `Timer` 回调里做长任务 | 回调堆叠、重入 | 加 `Interlocked` 重入保护，或用 `Task` 自循环 |
| `ConfigureAwait(true)` 在库代码 | 无谓的线程切换 | 库/服务层统一 `ConfigureAwait(false)`；UI 层不写 |
| 忘记 `UnobservedTaskException` | 静默失败 | 全局订阅并记日志 |

**`async void` 事件处理器的标准写法**：

```csharp
private async void btnStart_Click(object sender, EventArgs e)
{
    btnStart.Enabled = false;
    try
    {
        await _service.StartAsync();
    }
    catch (Exception ex)
    {
        _logger.Error(ex, "启动失败");
        MessageBox.Show(this, ex.Message, "启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
    finally
    {
        btnStart.Enabled = true;   // 用 try/finally 保证 UI 恢复
    }
}
```

### 7. 定时器选型

| 定时器 | 线程 | 适用 |
|---|---|---|
| `System.Windows.Forms.Timer` | UI 线程 | UI 刷新、动画、按钮防抖 |
| `System.Timers.Timer` | 线程池 | 一般后台定时，需手动处理重入 |
| `System.Threading.Timer` | 线程池 | 轻量高频，回调需自行保证不重入 |
| 自循环 `Task` + `Task.Delay(ct)` | 可 await | **推荐**，天然可取消、不重入、可 async |

**上位机推荐**：采集循环用 `自循环 Task + Task.Delay(ct)`；UI 刷新用 `WinForms.Timer`。避免 `System.Timers.Timer`（重入问题多，且异常会吞掉）。

### 8. 生产者-消费者落库管道

```csharp
public sealed class StoragePipeline : IDisposable
{
    private readonly BlockingCollection<Sample[]> _queue =
        new BlockingCollection<Sample[]>(boundedCapacity: 500);
    private readonly Task _consumer;

    public StoragePipeline(IRepository repo, CancellationToken ct)
    {
        _consumer = Task.Run(() => ConsumeAsync(repo, ct));
    }

    public bool TryEnqueue(Sample[] batch)
    {
        // 有界队列满时丢弃并告警，绝不阻塞采集线程
        if (!_queue.TryAdd(batch))
        {
            Interlocked.Increment(ref _dropped);
            return false;
        }
        return true;
    }

    private async Task ConsumeAsync(IRepository repo, CancellationToken ct)
    {
        var buffer = new List<Sample>(10000);
        foreach (var batch in _queue.GetConsumingEnumerable(ct))
        {
            buffer.AddRange(batch);
            if (buffer.Count >= 5000)
            {
                await repo.BulkInsertAsync(buffer, ct).ConfigureAwait(false);
                buffer.Clear();
            }
        }
    }

    public void Dispose() { _queue.CompleteAdding(); _consumer.Wait(3000); _queue.Dispose(); }
}
```

**核心思想：采集线程永不阻塞。队列满则丢弃 + 计数 + 告警，这比拖垮采集实时性可接受得多。**

---

## 第二部分：泛型与面向对象设计

### 9. 泛型抽象的三个层次

上位机设备接入统一用三层泛型抽象，**这是本技能的核心设计模式**。

```csharp
// 第 1 层：传输层 —— 只负责字节收发，不理解业务
public interface ITransport : IDisposable
{
    string Name { get; }
    bool IsOpen { get; }
    Task OpenAsync(CancellationToken ct);
    Task CloseAsync();
    Task<int> SendAsync(byte[] data, CancellationToken ct);
    Task<byte[]> ReceiveAsync(int expectedLength, TimeSpan timeout, CancellationToken ct);
    event EventHandler<TransportDataEventArgs> DataReceived;   // 事件驱动型（串口/TCP）
    event EventHandler<TransportStateEventArgs> StateChanged;  // 断线/重连
}

// 第 2 层：协议层 —— 帧解析、校验、请求-响应匹配
public interface IDeviceProtocol
{
    string Name { get; }
    byte[] BuildReadCommand(ProtocolReadRequest req);
    byte[] BuildWriteCommand(ProtocolWriteRequest req);
    ProtocolResponse Parse(byte[] rawFrame);       // 校验 + 解帧
    bool TryMatchResponse(byte[] buffer, out int frameLength);  // 用于粘包拆帧
}

// 第 3 层：设备层 —— 业务语义，泛型约束到协议
public interface IDeviceDriver<out TProtocol, TValue>
    where TProtocol : IDeviceProtocol
    where TValue : struct
{
    string DeviceId { get; }
    DeviceState State { get; }
    Task ConnectAsync(CancellationToken ct);
    Task<TValue> ReadAsync(string tag, CancellationToken ct);
    Task<IReadOnlyDictionary<string, TValue>> ReadBatchAsync(IEnumerable<string> tags, CancellationToken ct);
    Task WriteAsync(string tag, TValue value, CancellationToken ct);
    event EventHandler<TagValueChangedEventArgs<TValue>> TagValueChanged;
    event EventHandler<DeviceStateChangedEventArgs> StateChanged;
}
```

**泛型的价值**：`ReadBatchAsync` 返回强类型字典，避免 `object` 装箱与运行时转换错误；同时批量读取把 N 次通信压缩为 1 次，是 Modbus/OPC 性能关键。

### 10. 泛型工厂与注册表

```csharp
public interface IProtocolFactory
{
    IDeviceProtocol Create(string protocolName);
}

public sealed class ProtocolRegistry
{
    private readonly Dictionary<string, Func<IDeviceProtocol>> _creators =
        new Dictionary<string, Func<IDeviceProtocol>>(StringComparer.OrdinalIgnoreCase);

    public void Register(string name, Func<IDeviceProtocol> creator) => _creators[name] = creator;

    public IDeviceProtocol Create(string name)
    {
        if (!_creators.TryGetValue(name, out var f))
            throw new NotSupportedException($"未注册的协议：{name}");
        return f();
    }
}

// 泛型辅助：强类型标签地址
public sealed class TagAddress<T> where T : struct
{
    public string Raw { get; }
    public T Scale { get; }      // 换算系数
    public T Offset { get; }
    public string Unit { get; }

    public double Convert(double raw) => raw * Convert.ToDouble(Scale) + Convert.ToDouble(Offset);
}
```

### 11. 泛型约束的使用准则

```csharp
// ✅ 用 struct 约束数值标签，避免装箱
public class NumericTag<T> where T : struct, IComparable<T>, IConvertible { ... }

// ✅ 用 class 约束引用类型
public class Repository<TEntity> where TEntity : class, IEntity, new() { ... }

// ✅ 用接口约束表达能力需求
public class Poller<TDevice> where TDevice : IDeviceDriver<IProtocol, double> { ... }

// ❌ 禁止 where T : any（C# 不支持）；用接口 + 泛型方法替代
// ❌ 禁止为用泛型而泛型——只有 1 个具体类型时不抽象
```

**判定标准**：如果泛型约束只有一个实现类且短期无第二实现计划，先写具体类，等第二个实现出现时再抽象。**过度抽象是上位机项目最大的维护债。**

### 12. 面向对象设计准则

**SOLID 在上位机语境下的落地**：

| 原则 | 上位机落地要求 |
|---|---|
| S 单一职责 | 一个设备驱动只负责一个设备型号；解析与换算分离 |
| O 开闭 | 新设备型号 = 新增驱动类 + 配置注册，不改动已有代码 |
| L 里氏替换 | 所有 `ITransport` 实现（串口/TCP/虚拟）行为一致，可互换 |
| I 接口隔离 | 只读设备不实现 `IWriteableDevice`；不要把读写塞一个接口 |
| D 依赖倒置 | 业务层依赖 `ITransport`，不依赖 `SerialPort` |

**组合优于继承**：设备驱动用组合（持有 `ITransport` + `IDeviceProtocol`），不要用继承链（`SerialDevice : Device` 这种会爆炸）。

```csharp
// ✅ 组合
public sealed class ModbusRtuDriver : IDeviceDriver<ModbusProtocol, ushort>
{
    private readonly ITransport _transport;         // 串口或 TCP 均可注入
    private readonly ModbusProtocol _protocol;

    public ModbusRtuDriver(ITransport transport, ModbusProtocol protocol)
    {
        _transport = transport;
        _protocol = protocol;
    }
}

// ❌ 继承：一旦要支持 TCP，就要改基类或复制代码
// public class ModbusDevice : SerialDevice { }
```

### 13. 状态机（设备生命周期必用）

设备状态必须显式建模，禁止用多个 bool 拼状态。

```csharp
public sealed class DeviceStateMachine
{
    private static readonly Dictionary<DeviceState, DeviceState[]> Allowed =
        new Dictionary<DeviceState, DeviceState[]>
        {
            [DeviceState.Disconnected] = new[] { DeviceState.Connecting },
            [DeviceState.Connecting]   = new[] { DeviceState.Connected, DeviceState.Faulted },
            [DeviceState.Connected]    = new[] { DeviceState.Disconnected, DeviceState.Faulted },
            [DeviceState.Faulted]      = new[] { DeviceState.Reconnecting, DeviceState.Disconnected },
            [DeviceState.Reconnecting] = new[] { DeviceState.Connected, DeviceState.Faulted },
        };

    public DeviceState Current { get; private set; } = DeviceState.Disconnected;

    public bool TryTransition(DeviceState next)
    {
        if (!Allowed.TryGetValue(Current, out var targets) || Array.IndexOf(targets, next) < 0)
            return false;
        Current = next;
        return true;
    }
}
```

### 14. 重连与退避策略（必备）

```csharp
public sealed class ExponentialBackoff
{
    private readonly int _baseMs;
    private readonly int _maxMs;
    private int _attempt;

    public ExponentialBackoff(int baseMs = 500, int maxMs = 30000)
    { _baseMs = baseMs; _maxMs = maxMs; }

    public int NextDelayMs()
    {
        // 500, 1000, 2000, 4000, 8000, 16000, 30000, 30000...
        var delay = (int)Math.Min(_maxMs, _baseMs * Math.Pow(2, _attempt));
        _attempt++;
        return delay + ThreadLocalRandom.Next(0, 200);   // 加抖动，避免多设备同时重连
    }

    public void Reset() => _attempt = 0;
}
```

### 15. 可测试性要求

- **每个设备驱动必须配套一个 `SimulatedTransport`**（内存回环，按脚本返回报文），用于无硬件开发。
- 通信层可替代性由 `ITransport` 保证：单元测试注入 mock，集成测试注入 `SimulatedTransport`，现场注入真实实现。
- Domain 层算法必须 100% 可单测，不依赖任何 IO。

```csharp
public sealed class SimulatedTransport : ITransport
{
    private readonly Queue<byte[]> _scriptedResponses = new Queue<byte[]>();
    private readonly List<byte[]> _sentHistory = new List<byte[]>();

    public void EnqueueResponse(byte[] frame) => _scriptedResponses.Enqueue(frame);
    public IReadOnlyList<byte[]> SentHistory => _sentHistory;

    public Task<int> SendAsync(byte[] data, CancellationToken ct)
    {
        _sentHistory.Add((byte[])data.Clone());   // 记录以便断言
        return Task.FromResult(data.Length);
    }

    public Task<byte[]> ReceiveAsync(int expectedLength, TimeSpan timeout, CancellationToken ct)
    {
        if (_scriptedResponses.Count == 0)
            throw new TimeoutException("模拟传输无排队响应");
        return Task.FromResult(_scriptedResponses.Dequeue());
    }
    // 其余成员省略
}
```

### 16. 并发与泛型评审清单

- [ ] UI 线程是否存在 `.Result` / `.Wait()` / `Thread.Sleep`？
- [ ] 所有采集循环是否都可取消？取消后能否在 3 秒内退出？
- [ ] 环形缓冲是否会丢弃最旧数据而非崩溃？
- [ ] 落库队列是否有界？满队列策略是否明确（丢弃+告警）？
- [ ] 设备状态是否用状态机而非 bool 组合？
- [ ] 重连是否有指数退避 + 抖动？
- [ ] 每个 `IDisposable` 是否都有确定的释放路径？
- [ ] 是否可在无硬件条件下跑通业务（SimulatedTransport）？
- [ ] 泛型抽象是否存在过度设计（只有一个实现的接口）？
- [ ] `ConfigureAwait(false)` 是否只在库/服务层使用？
