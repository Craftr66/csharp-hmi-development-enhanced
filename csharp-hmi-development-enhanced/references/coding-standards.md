# 上位机 C# 编码规范

## 1. 命名规范

| 元素 | 规则 | 示例 |
|---|---|---|
| 类 / 结构 / 接口 | PascalCase；接口前缀 `I` | `DeviceManager`, `ITransport` |
| 方法 | PascalCase，动词开头 | `ReadBatchAsync` |
| 属性 | PascalCase | `IsConnected` |
| 公有字段 | **禁止**，一律用属性 | — |
| 私有字段 | `_camelCase` | `_logger`, `_cts` |
| 局部变量 | camelCase | `frameLength` |
| 常量 | PascalCase（不用全大写） | `MaxRetryCount` |
| 静态只读 | PascalCase | `DefaultTimeout` |
| 枚举 | PascalCase，值也是 PascalCase | `DeviceState.Connected` |
| 泛型参数 | `T` 前缀 | `TValue`, `TProtocol` |
| 事件 | PascalCase，不用 `On` 前缀（`On` 留给触发方法） | `event EventHandler ValueChanged;` |
| 触发方法 | `On` + 事件名，`protected virtual` | `protected virtual void OnValueChanged()` |
| 异步方法 | 后缀 `Async` | `ReadAsync` |
| 布尔成员 | `Is` / `Has` / `Can` 前缀 | `IsOpen`, `CanWrite` |

## 2. 格式与组织

```csharp
// 文件结构顺序：
// 1. using 指令（System 在前，第三方在后，空行分隔）
// 2. namespace
// 3. 类注释（XML）
// 4. 常量 / 字段
// 5. 构造函数
// 6. 事件
// 7. 属性
// 8. 公有方法
// 9. 私有方法
// 10. 内部类

// 4 空格缩进，不用 Tab
// 大括号独占一行（Allman 风格）
// 单行不超过 120 字符
// 成员之间空一行
```

## 3. 上位机专用规则

### 3.1 线程与异步

```csharp
// ✅ 后台任务返回 Task，只有事件处理器用 async void
private async void btnStart_Click(object sender, EventArgs e) { }

// ✅ 后台任务必须可取消
private async Task RunAsync(CancellationToken ct)

// ✅ 库/服务层用 ConfigureAwait(false)，UI 层不写
await stream.ReadAsync(buffer, 0, len, ct).ConfigureAwait(false);

// ❌ 禁止 UI 线程阻塞等待
var result = SomeAsync().Result;      // 死锁
SomeAsync().Wait();                   // 死锁
Thread.Sleep(1000);                   // 卡界面

// ❌ 禁止在后台线程直接访问控件
label.Text = "x";                     // 跨线程异常
// ✅
label.SafeInvoke(() => label.Text = "x");
```

### 3.2 资源释放

```csharp
// ✅ 实现 IDisposable 的标准模式
public sealed class DeviceManager : IDisposable
{
    private bool _disposed;
    private readonly List<IDisposable> _resources = new List<IDisposable>();

    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    private void Dispose(bool disposing)
    {
        if (_disposed) return;
        if (disposing)
        {
            foreach (var r in _resources)
            {
                try { r?.Dispose(); }
                catch (Exception ex) { _logger?.Warn($"释放资源异常：{ex.Message}"); }
            }
            _resources.Clear();
        }
        _disposed = true;
    }
    // 禁用终结器（除非持有非托管资源，且用了 SafeHandle 时也不需要）
}

// ✅ using 包裹短生命周期资源
using (var cts = CancellationTokenSource.CreateLinkedTokenSource(ct)) { }
```

### 3.3 异常处理

```csharp
// ❌ 禁止空捕获
try { ... } catch { }

// ❌ 禁止宽泛捕获后不处理
try { ... } catch (Exception) { /* 什么都不做 */ }

// ✅ 区分可重试与不可重试
catch (TimeoutException) { /* 可重试 */ }
catch (CrcException) { /* 可重试，记录并重发 */ }
catch (UnauthorizedAccessException) { /* 不可重试：端口被占用 */ }
catch (IOException) { /* 可能需要重连 */ }
catch (OperationCanceledException) { /* 正常退出，不记 Error */ }

// ✅ 异常信息要带上下文
throw new IOException($"串口 {_portName} 打开失败（被占用？）", ex);

// ✅ 自定义异常层次
public class HmiException : Exception { }
public class ProtocolException : HmiException { }
public class CrcException : ProtocolException { }
public class DeviceCommunicationException : HmiException { }
public class ConfirmRequiredException : HmiException { }
```

### 3.4 日志

```csharp
// ❌ 高频路径避免字符串拼接
_logger.Trace("RX: " + BitConverter.ToString(data));      // 每次都拼接

// ✅ 使用参数化（NLog 支持延迟格式化）
_logger.Trace("RX[{0}] {1}", Name, ToHex(data));

// ✅ 高频日志用级别守卫
if (_logger.IsTraceEnabled) _logger.Trace(...);

// ✅ 异常必须带上下文
_logger.Error(ex, "设备 {0} 读取标签 {1} 失败", DeviceId, tag);

// ❌ 禁止在日志里泄露密码
_logger.Info($"登录用户={user} 密码={password}");   // 绝对禁止
```

### 3.5 数值与转换

```csharp
// ✅ 显式转换 + 范围检查
if (value < ushort.MinValue || value > ushort.MaxValue)
    throw new ArgumentOutOfRangeException(nameof(value), $"值 {value} 超出 ushort 范围");
ushort v = (ushort)value;

// ✅ 浮点比较用容差
if (Math.Abs(a - b) < 1e-6) { }

// ✅ 量纲换算集中管理，不散落各处
double physical = raw * tag.Scale + tag.Offset;

// ❌ 禁止隐式截断
int x = (int)someDouble;    // 先检查范围
```

## 4. 禁用项清单

| 禁用 | 原因 | 替代 |
|---|---|---|
| `Thread.Sleep` | 不可取消，阻塞线程 | `await Task.Delay(ms, ct)` |
| `.Result` / `.Wait()` | UI 线程死锁 | `await` |
| `Control.Invoke` | 后台线程阻塞等待 | `Control.BeginInvoke` |
| `async void`（非事件） | 异常丢失 | `async Task` |
| `Application.DoEvents()` | 重入、状态混乱 | 真正的异步 |
| `catch { }` | 静默失败 | 至少记日志 |
| `GC.Collect()` | 破坏 GC 策略 | 修复泄漏根因 |
| 硬编码 IP/路径/密码 | 现场无法调整、安全风险 | 配置文件（密码加密） |
| `static` 可变字段 | 并发问题、无法测试 | 实例字段 + 依赖注入 |
| 公有字段 | 无法加校验与通知 | 属性 |
| `lock(this)` / `lock(typeof(T))` | 外部可锁导致死锁 | `private readonly object _lock` |
| `string` 拼接循环 | O(n²) | `StringBuilder` |
| 未限定队列容量 | 内存爆炸 | 有界队列 + 溢出策略 |
| 一次 `Write` 超 64KB | 阻塞 | 分片 |
| 浮点做金额计算 | 精度丢失 | `decimal` |
| 硬编码小数点位数 | 无法适配 | 配置 |

## 5. 注释规范

```csharp
/// <summary>
/// 批量读取多个标签的值。内部会自动合并连续地址以减少通信次数。
/// </summary>
/// <param name="tags">标签名集合，须已在配置中定义</param>
/// <param name="ct">取消令牌</param>
/// <returns>标签名到值的映射；读取失败的标签不会出现在结果中</returns>
/// <exception cref="DeviceCommunicationException">设备未连接或通信失败</exception>
/// <exception cref="OperationCanceledException">操作被取消</exception>
/// <remarks>
/// 现场注意：单次请求的寄存器总数受设备限制（通常 125），
/// 本方法会自动分块，但分块会增加总耗时。
/// </remarks>
public async Task<IReadOnlyDictionary<string, ushort>> ReadBatchAsync(
    IEnumerable<string> tags, CancellationToken ct)

// 为什么这样写（而非写"做了什么"）
// ⚠️ 必须关闭 Nagle，否则小报文会被延迟 40ms 合并
_client.NoDelay = true;

// TODO 需登记到问题台账
// TODO(ISS-023): 分段 SDO 暂未实现，需在 V1.2 补充
```

## 6. 配置项规范

```csharp
// ❌ 硬编码
if (timeout > 3000) { }

// ❌ 魔数
await Task.Delay(200);

// ✅ 具名常量或配置
private static readonly TimeSpan DefaultRetryInterval = TimeSpan.FromMilliseconds(200);
if (timeout > _cfg.MaxTimeoutMs) { }
```

**必须外置的配置**：设备地址与通信参数、超时与重试、采集周期、文件路径、数据库连接、日志级别与保留期、界面可调参数、报警阈值、权限矩阵。

**可以硬编码的**：协议常量（CRC 多项式、帧头字节）、物理常量、算法系数。

## 7. 代码评审自查清单

- [ ] 是否有 `.Result` / `.Wait()` / `Thread.Sleep`？
- [ ] 是否所有后台任务都可取消？
- [ ] 是否有空 catch 或吞异常？
- [ ] 是否所有 IDisposable 都有释放路径？
- [ ] 事件是否都有对应的取消订阅？
- [ ] 是否所有现场可变参数都外置？
- [ ] 是否所有跨线程控件访问都走 SafeInvoke？
- [ ] 是否有硬编码路径/IP/密码？
- [ ] 是否所有数值转换都有范围检查？
- [ ] 是否有超长方法（>80 行）需要拆分？
- [ ] 是否有重复代码（>3 处相同逻辑）需要提取？
- [ ] 关键类与方法是否有 XML 注释？
- [ ] 是否所有 public 成员都必要（能否 internal）？
- [ ] 是否有 `static` 可变状态？
- [ ] 是否有 TODO 未登记到问题台账？
