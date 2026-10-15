// =============================================================================
// 新设备驱动接入模板
// =============================================================================
// 使用方法：
//   1. 复制本文件，重命名为 <设备型号>Driver.cs
//   2. 替换所有 TODO 标记
//   3. 在 DeviceManager 中注册（新增一行，不改其他代码）
//   4. 配套编写 SimulatedTransport 的响应脚本用于单测
//
// 设计原则：
//   - 组合优于继承：持有 ITransport + IDeviceProtocol，不继承基类
//   - 单一职责：本类只做"业务语义 ↔ 协议报文"的映射
//   - 不猜硬件：所有地址、字节序、范围必须来自配置或已确认的手册
// =============================================================================

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace SolutionName.Comm.Devices
{
    /// <summary>
    /// TODO: 填写设备型号与协议说明。
    /// 例：XX 品牌 YY 型号温控器，Modbus RTU，从站地址可配置。
    /// </summary>
    /// <remarks>
    /// 现场注意事项：
    ///   - TODO: 填写该设备特有的坑
    ///   - 例：写入设定值后需延时 300ms 才会生效，需回读确认
    /// </remarks>
    public sealed class TodoDeviceDriver : IDeviceDriver<IDeviceProtocol, double>, IDisposable
    {
        // ---------------------------------------------------------------------
        // 依赖（构造注入，禁止在内部 new）
        // ---------------------------------------------------------------------
        private readonly ITransport _transport;
        private readonly IDeviceProtocol _protocol;
        private readonly ILogService _logger;
        private readonly TodoDeviceConfig _cfg;

        // ---------------------------------------------------------------------
        // 同步原语
        // ---------------------------------------------------------------------
        /// <summary>该设备的 IO 互斥锁。协议通常不支持并发请求，必须串行化。</summary>
        private readonly SemaphoreSlim _ioLock = new SemaphoreSlim(1, 1);

        /// <summary>标签定义缓存，避免每次读取都线性查找。</summary>
        private readonly ConcurrentDictionary<string, TagDefinition> _tagMap;

        /// <summary>标签最新值缓存。</summary>
        private readonly ConcurrentDictionary<string, double> _valueCache
            = new ConcurrentDictionary<string, double>();

        // ---------------------------------------------------------------------
        // 状态
        // ---------------------------------------------------------------------
        private DeviceState _state = DeviceState.Disconnected;
        private bool _disposed;

        public string DeviceId => _cfg.Id;

        public DeviceState State
        {
            get => _state;
            private set
            {
                if (_state == value) return;
                _state = value;
                // TODO: 触发事件时注意线程上下文，UI 侧需自行封送
                StateChanged?.Invoke(this, new DeviceStateChangedEventArgs(DeviceId, value));
                _logger.Info($"设备 {DeviceId} 状态：{value}");
            }
        }

        public event EventHandler<TagValueChangedEventArgs<double>> TagValueChanged;
        public event EventHandler<DeviceStateChangedEventArgs> StateChanged;

        // ---------------------------------------------------------------------
        // 构造
        // ---------------------------------------------------------------------
        public TodoDeviceDriver(
            TodoDeviceConfig cfg,
            ITransport transport,
            IDeviceProtocol protocol,
            ILogService logger)
        {
            _cfg = cfg ?? throw new ArgumentNullException(nameof(cfg));
            _transport = transport ?? throw new ArgumentNullException(nameof(transport));
            _protocol = protocol ?? throw new ArgumentNullException(nameof(protocol));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));

            // 校验配置（宁可启动失败，也不要运行到一半才出错）
            ValidateConfig(cfg);

            _tagMap = new ConcurrentDictionary<string, TagDefinition>(
                cfg.Tags.ToDictionary(t => t.Name, t => t),
                StringComparer.OrdinalIgnoreCase);
        }

        private static void ValidateConfig(TodoDeviceConfig cfg)
        {
            if (string.IsNullOrWhiteSpace(cfg.Id))
                throw new ConfigException("设备 Id 不能为空");

            if (cfg.Tags == null || cfg.Tags.Count == 0)
                throw new ConfigException($"设备 {cfg.Id} 未配置任何标签");

            // 检查标签名重复
            var dup = cfg.Tags.GroupBy(t => t.Name).Where(g => g.Count() > 1).ToList();
            if (dup.Count > 0)
                throw new ConfigException(
                    $"设备 {cfg.Id} 存在重复标签名：{string.Join(", ", dup.Select(g => g.Key))}");

            // 检查写入标签是否有范围限制
            foreach (var t in cfg.Tags.Where(x => x.Access == TagAccess.ReadWrite))
            {
                if (!t.MinValue.HasValue || !t.MaxValue.HasValue)
                    _logger.Warn($"可写标签 {t.Name} 未配置上下限，存在误写风险，建议补充");
            }

            // TODO: 添加该设备特有的校验
        }

        // ---------------------------------------------------------------------
        // 连接
        // ---------------------------------------------------------------------
        public async Task ConnectAsync(CancellationToken ct)
        {
            await _ioLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                if (_transport.IsOpen && State == DeviceState.Connected) return;

                State = DeviceState.Connecting;

                if (!_transport.IsOpen)
                    await _transport.OpenAsync(ct).ConfigureAwait(false);

                // TODO: 设备特定的连接后初始化
                // 例：读取设备型号确认、发送使能命令、清故障
                await InitializeDeviceAsync(ct).ConfigureAwait(false);

                State = DeviceState.Connected;
                _logger.Info($"设备 {DeviceId} 连接成功");
            }
            catch (OperationCanceledException)
            {
                State = DeviceState.Disconnected;
                throw;
            }
            catch (Exception ex)
            {
                State = DeviceState.Faulted;
                _logger.Error(ex, $"设备 {DeviceId} 连接失败");
                throw new DeviceCommunicationException($"设备 {DeviceId} 连接失败", ex);
            }
            finally { _ioLock.Release(); }
        }

        /// <summary>TODO: 连接后的设备初始化序列</summary>
        private async Task InitializeDeviceAsync(CancellationToken ct)
        {
            // 例：读取设备型号验证
            // var model = await SendAndReceiveAsync("读型号命令", ct);
            // if (model != _cfg.ExpectedModel)
            //     throw new ProtocolException($"设备型号不匹配：期望 {_cfg.ExpectedModel}，实际 {model}");
            await Task.CompletedTask;
        }

        public async Task DisconnectAsync()
        {
            try
            {
                await _ioLock.WaitAsync().ConfigureAwait(false);
                try
                {
                    if (_transport.IsOpen) await _transport.CloseAsync().ConfigureAwait(false);
                }
                finally { _ioLock.Release(); }
            }
            catch (Exception ex)
            {
                _logger.Warn($"设备 {DeviceId} 断开时异常：{ex.Message}");
            }
            finally { State = DeviceState.Disconnected; }
        }

        // ---------------------------------------------------------------------
        // 读取
        // ---------------------------------------------------------------------
        public async Task<double> ReadAsync(string tag, CancellationToken ct)
        {
            var result = await ReadBatchAsync(new[] { tag }, ct).ConfigureAwait(false);
            if (!result.TryGetValue(tag, out double v))
                throw new DeviceCommunicationException($"设备 {DeviceId} 读取标签 {tag} 失败");
            return v;
        }

        /// <summary>
        /// 批量读取。TODO: 若协议支持地址归并，替换为批量规划实现（性能提升可达 10-50 倍）。
        /// </summary>
        public async Task<IReadOnlyDictionary<string, double>> ReadBatchAsync(
            IEnumerable<string> tags, CancellationToken ct)
        {
            var names = tags?.ToList() ?? new List<string>();
            if (names.Count == 0) return new Dictionary<string, double>();

            // 解析标签定义
            var defs = new List<TagDefinition>();
            foreach (var n in names)
            {
                if (!_tagMap.TryGetValue(n, out var def))
                    throw new ArgumentException($"设备 {DeviceId} 未定义标签 {n}", nameof(tags));
                defs.Add(def);
            }

            await _ioLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                EnsureConnected();

                // TODO: 替换为地址归并 + 批量读取
                // 示例（单点读取，仅作占位）：
                var result = new Dictionary<string, double>();
                foreach (var def in defs)
                {
                    ct.ThrowIfCancellationRequested();
                    try
                    {
                        double raw = await ReadSingleAsync(def, ct).ConfigureAwait(false);
                        double physical = raw * def.Scale + def.Offset;

                        // 数据有效性校验
                        if (double.IsNaN(physical) || double.IsInfinity(physical))
                        {
                            _logger.Warn($"设备 {DeviceId} 标签 {def.Name} 返回非法值 {raw}");
                            continue;
                        }

                        result[def.Name] = physical;
                        PublishIfChanged(def.Name, physical);
                    }
                    catch (Exception ex)
                    {
                        // 单点失败不影响其他点
                        _logger.Warn($"设备 {DeviceId} 读取标签 {def.Name} 失败：{ex.Message}");
                    }
                }
                return result;
            }
            finally { _ioLock.Release(); }
        }

        private async Task<double> ReadSingleAsync(TagDefinition def, CancellationToken ct)
        {
            // TODO: 使用 _protocol 构造读命令并解析响应
            // var req = new ProtocolReadRequest(def.WireAddress, 1, def.FunctionCode);
            // var frame = _protocol.BuildReadCommand(req);
            // await _transport.SendAsync(frame, ct);
            // int expected = <按协议计算响应长度>;
            // var raw = await _transport.ReceiveAsync(expected, _cfg.ReadTimeout, ct);
            // var resp = _protocol.Parse(raw);
            // return resp.Registers[0];

            throw new NotImplementedException("TODO: 实现 ReadSingleAsync");
        }

        private void PublishIfChanged(string tag, double value)
        {
            bool changed = !_valueCache.TryGetValue(tag, out double old)
                           || Math.Abs(old - value) > 1e-9;
            _valueCache[tag] = value;

            if (changed)
                TagValueChanged?.Invoke(this, new TagValueChangedEventArgs<double>(
                    tag, value, DateTime.UtcNow, 0));
        }

        // ---------------------------------------------------------------------
        // 写入
        // ---------------------------------------------------------------------
        public async Task WriteAsync(string tag, double value, CancellationToken ct)
        {
            if (!_tagMap.TryGetValue(tag, out var def))
                throw new ArgumentException($"设备 {DeviceId} 未定义标签 {tag}", nameof(tag));

            // ---- 安全校验（必须全部通过才允许写入）----
            if (def.Access != TagAccess.ReadWrite)
                throw new InvalidOperationException($"设备 {DeviceId} 标签 {tag} 为只读，禁止写入");

            if (def.MinValue.HasValue && value < def.MinValue.Value)
                throw new ArgumentOutOfRangeException(nameof(value),
                    $"值 {value} 低于下限 {def.MinValue.Value}（标签 {tag}）");

            if (def.MaxValue.HasValue && value > def.MaxValue.Value)
                throw new ArgumentOutOfRangeException(nameof(value),
                    $"值 {value} 高于上限 {def.MaxValue.Value}（标签 {tag}）");

            if (_state != DeviceState.Connected)
                throw new DeviceCommunicationException($"设备 {DeviceId} 未连接，禁止写入");

            // TODO: 若设备有运行状态联锁（如运行中禁止写），在此检查
            // if (_isRunning) throw new InvalidOperationException("设备运行中禁止修改该参数");

            double oldValue = _valueCache.TryGetValue(tag, out double ov) ? ov : double.NaN;
            double raw = (value - def.Offset) / (def.Scale == 0 ? 1 : def.Scale);

            await _ioLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                EnsureConnected();

                // TODO: 使用 _protocol 构造写命令并发送
                // var req = new ProtocolWriteRequest(def.WireAddress, new[]{ (ushort)raw });
                // var frame = _protocol.BuildWriteCommand(req);
                // await _transport.SendAsync(frame, ct);
                // var respRaw = await _transport.ReceiveAsync(8, _cfg.WriteTimeout, ct);
                // _protocol.Parse(respRaw);   // 抛异常表示失败

                // 操作日志（可追溯）
                _logger.Info(
                    $"设备 {DeviceId} 写入 {tag}：{oldValue:F3} → {value:F3}（原始值 {raw:F3}）");

                _valueCache[tag] = value;

                // TODO: 若设备有"写后延时生效"，在此延时并回读校验
                // await Task.Delay(_cfg.WriteSettleMs, ct);
                // var readback = await ReadAsync(tag, ct);
                // if (Math.Abs(readback - value) > def.Tolerance)
                //     throw new ProtocolException($"写入未生效：期望 {value}，回读 {readback}");
            }
            catch (OperationCanceledException) { throw; }
            catch (Exception ex)
            {
                _logger.Error(ex, $"设备 {DeviceId} 写入标签 {tag} 失败");
                throw;
            }
            finally { _ioLock.Release(); }
        }

        // ---------------------------------------------------------------------
        // 辅助
        // ---------------------------------------------------------------------
        private void EnsureConnected()
        {
            if (_state != DeviceState.Connected || !_transport.IsOpen)
                throw new DeviceCommunicationException($"设备 {DeviceId} 未连接");
        }

        /// <summary>供诊断包使用</summary>
        public string DumpStateSnapshot()
        {
            var sb = new System.Text.StringBuilder();
            sb.AppendLine($"设备: {DeviceId}");
            sb.AppendLine($"状态: {_state}");
            sb.AppendLine($"传输: {_transport.Name} 已打开={_transport.IsOpen}");
            sb.AppendLine("标签值:");
            foreach (var kv in _valueCache.OrderBy(k => k.Key))
                sb.AppendLine($"  {kv.Key} = {kv.Value}");
            return sb.ToString();
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;

            try { _transport?.Dispose(); }
            catch (Exception ex) { _logger?.Warn($"释放设备 {DeviceId} 传输异常：{ex.Message}"); }

            try { _ioLock.Dispose(); } catch { }
        }
    }

    // =========================================================================
    // 配置模型
    // =========================================================================
    public sealed class TodoDeviceConfig
    {
        public string Id { get; set; }
        public string Name { get; set; }

        /// <summary>协议名，用于工厂创建（如 "ModbusRtu"）</summary>
        public string Protocol { get; set; }

        /// <summary>端点，如 "COM3" 或 "192.168.1.10:502"</summary>
        public string Endpoint { get; set; }

        /// <summary>从站地址 / UnitId</summary>
        public byte SlaveId { get; set; } = 1;

        /// <summary>字节序（Modbus 类协议必需）</summary>
        public string Endian { get; set; } = "ABCD";

        public int ReadTimeoutMs { get; set; } = 1000;
        public int WriteTimeoutMs { get; set; } = 1000;
        public int RetryCount { get; set; } = 3;

        /// <summary>写后延时生效时间，0 表示无需等待</summary>
        public int WriteSettleMs { get; set; }

        public List<TagDefinition> Tags { get; set; } = new List<TagDefinition>();
    }
}
