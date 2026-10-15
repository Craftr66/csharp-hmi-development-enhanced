# TCP / UDP 通信实现规范

## 1. 选型对照

| 场景 | 选择 | 理由 |
|---|---|---|
| PLC / 智能仪表 / 网关 | **TCP** | 可靠，能感知断线 |
| 高频数据流（图像、波形） | TCP（或 UDP + 应用层序号） | 需保证顺序 |
| 广播下发、设备发现 | **UDP 广播** | 一次发多收 |
| 毫秒级实时、容忍丢包 | UDP | 无重传延迟 |
| 上位机做服务端被下位机连入 | TCP Server | 设备主动上报场景 |

**决策原则：上位机与工控设备之间，默认用 TCP。** UDP 仅用于设备发现与广播同步。

## 2. TCP 客户端（上位机主动连设备）

```csharp
using System;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;

public sealed class TcpClientTransport : ITransport
{
    private readonly IPEndPoint _endpoint;
    private readonly ILogService _logger;
    private readonly int _connectTimeoutMs;
    private TcpClient _client;
    private NetworkStream _stream;
    private readonly SemaphoreSlim _sendLock = new SemaphoreSlim(1, 1);
    private readonly object _sync = new object();

    public string Name => $"{_endpoint.Address}:{_endpoint.Port}";
    public bool IsOpen => _client != null && _client.Connected;

    public event EventHandler<TransportDataEventArgs> DataReceived;
    public event EventHandler<TransportStateEventArgs> StateChanged;

    public TcpClientTransport(string hostOrIp, int port, ILogService logger, int connectTimeoutMs = 3000)
    {
        _endpoint = new IPEndPoint(ResolveHost(hostOrIp), port);
        _logger = logger;
        _connectTimeoutMs = connectTimeoutMs;
    }

    private static IPAddress ResolveHost(string host)
    {
        if (IPAddress.TryParse(host, out var ip)) return ip;
        var addrs = Dns.GetHostAddresses(host);
        if (addrs.Length == 0) throw new ArgumentException($"无法解析主机名：{host}");
        return addrs[0];
    }

    public async Task OpenAsync(CancellationToken ct)
    {
        CloseInternal();
        _client = new TcpClient();

        // ⚠️ .NET Framework 4.8 无 ConnectAsync(host, port, ct) 重载，
        //    需用 Task.WhenAny + Delay 实现可控超时
        using (var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct))
        {
            timeoutCts.CancelAfter(_connectTimeoutMs);
            try
            {
                await _client.ConnectAsync(_endpoint.Address, _endpoint.Port).ConfigureAwait(false);
            }
            catch (SocketException ex)
            {
                _logger.Error(ex, $"连接 {Name} 失败，SocketError={ex.SocketErrorCode}");
                throw new IOException($"连接 {Name} 失败：{ex.SocketErrorCode}", ex);
            }
        }

        // ⚠️ 必须关闭 Nagle 算法，否则小报文会被延迟合并（典型 40ms 延迟）
        _client.NoDelay = true;
        _client.ReceiveTimeout = 1000;
        _client.SendTimeout = 1000;

        // TCP KeepAlive：检测半开连接（网线被拔但 socket 无感知）
        _client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.KeepAlive, true);
        ConfigureKeepAlive(_client.Client, keepAliveTimeMs: 5000, keepAliveIntervalMs: 1000);

        _stream = _client.GetStream();
        StateChanged?.Invoke(this, new TransportStateEventArgs(TransportState.Opened, null));
        _logger.Info($"TCP {Name} 已连接");
    }

    /// <summary>配置 TCP KeepAlive 参数（需 P/Invoke，.NET Framework 无托管 API）</summary>
    private static void ConfigureKeepAlive(Socket socket, int keepAliveTimeMs, int keepAliveIntervalMs)
    {
        try
        {
            // SIO_KEEPALIVE_VALS = 0x98000004，结构为 (onoff, keepalivetime, keepaliveinterval)
            byte[] inValue = new byte[12];
            BitConverter.GetBytes(1u).CopyTo(inValue, 0);
            BitConverter.GetBytes((uint)keepAliveTimeMs).CopyTo(inValue, 4);
            BitConverter.GetBytes((uint)keepAliveIntervalMs).CopyTo(inValue, 8);
            socket.IOControl(IOControlCode.KeepAliveValues, inValue, null);
        }
        catch { /* 某些平台不支持，忽略 */ }
    }

    public Task CloseAsync()
    {
        CloseInternal();
        StateChanged?.Invoke(this, new TransportStateEventArgs(TransportState.Closed, null));
        return Task.FromResult(true);
    }

    private void CloseInternal()
    {
        lock (_sync)
        {
            try { _stream?.Close(); } catch { }
            try { _client?.Close(); } catch { }
            _stream = null;
            _client = null;
        }
    }

    public async Task<int> SendAsync(byte[] data, CancellationToken ct)
    {
        await _sendLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var s = _stream;
            if (s == null) throw new InvalidOperationException($"TCP {Name} 未连接");
            await s.WriteAsync(data, 0, data.Length, ct).ConfigureAwait(false);
            await s.FlushAsync(ct).ConfigureAwait(false);
            _logger.Trace($"TX[{Name}] {ToHex(data)}");
            return data.Length;
        }
        finally { _sendLock.Release(); }
    }

    public async Task<byte[]> ReceiveAsync(int expectedLength, TimeSpan timeout, CancellationToken ct)
    {
        var s = _stream ?? throw new InvalidOperationException($"TCP {Name} 未连接");
        var buffer = new byte[expectedLength];
        int offset = 0;

        using (var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct))
        {
            timeoutCts.CancelAfter(timeout);
            try
            {
                while (offset < expectedLength)
                {
                    int n = await s.ReadAsync(buffer, offset, expectedLength - offset, timeoutCts.Token)
                                   .ConfigureAwait(false);
                    if (n == 0) throw new IOException($"TCP {Name} 连接被对端关闭（收到 0 字节）");
                    offset += n;
                }
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                throw new TimeoutException($"TCP {Name} 接收超时：期望 {expectedLength}，实收 {offset}");
            }
        }

        _logger.Trace($"RX[{Name}] {ToHex(buffer)}");
        return buffer;
    }

    private static string ToHex(byte[] d) => BitConverter.ToString(d).Replace("-", " ");
}
```

### 2.1 持续接收循环（长连接必备）

长连接需要独立接收任务，不能靠 `ReceiveAsync` 按需读。

```csharp
public sealed class TcpReceiveLoop : IDisposable
{
    private readonly TcpClientTransport _transport;
    private readonly ILogService _logger;
    private readonly Func<byte[], int, int> _onFrame;   // 帧处理器，返回已消费字节数
    private Task _loop;
    private CancellationTokenSource _cts;

    public void Start(CancellationToken externalCt)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(externalCt);
        _loop = Task.Run(() => RunAsync(_cts.Token));
    }

    private async Task RunAsync(CancellationToken ct)
    {
        var buffer = new byte[8192];
        var accum = new MemoryStream(65536);

        while (!ct.IsCancellationRequested)
        {
            try
            {
                int n = await _transport.ReadIntoBufferAsync(buffer, ct).ConfigureAwait(false);
                if (n <= 0) throw new IOException("连接已断开");

                accum.Write(buffer, 0, n);

                // 持续从累积缓冲中拆帧，直到无完整帧
                while (true)
                {
                    var data = accum.ToArray();
                    int consumed = _onFrame(data, 0, data.Length);
                    if (consumed <= 0) break;

                    accum.SetLength(0);
                    accum.Write(data, consumed, data.Length - consumed);
                }

                // ⚠️ 防止畸形数据导致缓冲无限增长
                if (accum.Length > 1_048_576)
                {
                    _logger.Warn("接收缓冲超过 1MB，疑似协议错位，已清空");
                    accum.SetLength(0);
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                _logger.Error(ex, "TCP 接收循环异常，将触发重连");
                break;
            }
        }
    }

    public void Dispose()
    {
        try { _cts?.Cancel(); } catch { }
        try { _loop?.Wait(2000); } catch { }
        _cts?.Dispose();
        _cts = null;
    }
}
```

## 3. TCP 服务端（上位机接收设备主动上报）

```csharp
public sealed class TcpServerTransport : IDisposable
{
    private readonly TcpListener _listener;
    private readonly ILogService _logger;
    private readonly ConcurrentDictionary<string, TcpClient> _clients =
        new ConcurrentDictionary<string, TcpClient>();
    private readonly int _maxClients;
    private CancellationTokenSource _cts;

    public event EventHandler<ClientEventArgs> ClientConnected;
    public event EventHandler<ClientEventArgs> ClientDisconnected;
    public event EventHandler<ClientDataEventArgs> DataReceived;

    public TcpServerTransport(int port, int maxClients, ILogService logger)
    {
        _listener = new TcpListener(IPAddress.Any, port);
        _maxClients = maxClients;
        _logger = logger;
    }

    public void Start(CancellationToken ct)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _listener.Start();
        _logger.Info($"TCP 服务端已监听端口 {((IPEndPoint)_listener.LocalEndpoint).Port}");
        Task.Run(() => AcceptLoopAsync(_cts.Token));
    }

    private async Task AcceptLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var client = await _listener.AcceptTcpClientAsync().ConfigureAwait(false);

                if (_clients.Count >= _maxClients)
                {
                    _logger.Warn($"客户端数已达上限 {_maxClients}，拒绝 {client.Client.RemoteEndPoint}");
                    client.Close();
                    continue;
                }

                client.NoDelay = true;
                var key = client.Client.RemoteEndPoint.ToString();
                _clients[key] = client;
                ClientConnected?.Invoke(this, new ClientEventArgs(key));

                Task.Run(() => ClientLoopAsync(key, client, ct));
            }
            catch (ObjectDisposedException) { break; }
            catch (Exception ex)
            {
                _logger.Error(ex, "接受连接异常");
                await Task.Delay(200, ct).ConfigureAwait(false);
            }
        }
    }

    private async Task ClientLoopAsync(string key, TcpClient client, CancellationToken ct)
    {
        var buffer = new byte[8192];
        try
        {
            var stream = client.GetStream();
            while (!ct.IsCancellationRequested)
            {
                int n = await stream.ReadAsync(buffer, 0, buffer.Length, ct).ConfigureAwait(false);
                if (n == 0) break;
                DataReceived?.Invoke(this, new ClientDataEventArgs(key, buffer, n));
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex) { _logger.Warn($"客户端 {key} 异常断开：{ex.Message}"); }
        finally
        {
            _clients.TryRemove(key, out _);
            try { client.Close(); } catch { }
            ClientDisconnected?.Invoke(this, new ClientEventArgs(key));
        }
    }

    public Task SendToAsync(string clientKey, byte[] data, CancellationToken ct)
    {
        if (!_clients.TryGetValue(clientKey, out var c)) throw new InvalidOperationException($"客户端 {clientKey} 不存在");
        return c.GetStream().WriteAsync(data, 0, data.Length, ct);
    }

    public async Task BroadcastAsync(byte[] data, CancellationToken ct)
    {
        foreach (var kv in _clients.ToArray())
        {
            try { await kv.Value.GetStream().WriteAsync(data, 0, data.Length, ct).ConfigureAwait(false); }
            catch (Exception ex) { _logger.Warn($"广播到 {kv.Key} 失败：{ex.Message}"); }
        }
    }

    public void Dispose()
    {
        try { _cts?.Cancel(); } catch { }
        try { _listener.Stop(); } catch { }
        foreach (var kv in _clients.ToArray()) { try { kv.Value.Close(); } catch { } }
        _clients.Clear();
        _cts?.Dispose();
    }
}
```

## 4. UDP 通信

```csharp
public sealed class UdpTransport : ITransport
{
    private UdpClient _udp;
    private readonly IPEndPoint _remote;
    private CancellationTokenSource _cts;

    public UdpTransport(string remoteIp, int remotePort, int localPort = 0)
    {
        _udp = new UdpClient(localPort);
        // ⚠️ 必须允许端口复用，否则上位机重启会因端口未释放而失败
        _udp.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
        // 广播需开启
        _udp.EnableBroadcast = true;
        _remote = new IPEndPoint(IPAddress.Parse(remoteIp), remotePort);
    }

    public Task<int> SendAsync(byte[] data, CancellationToken ct)
        => _udp.SendAsync(data, data.Length, _remote);

    public async Task<byte[]> ReceiveAsync(int expectedLength, TimeSpan timeout, CancellationToken ct)
    {
        var tcs = new TaskCompletionSource<UdpReceiveResult>();
        using (_cts = CancellationTokenSource.CreateLinkedTokenSource(ct))
        {
            _cts.CancelAfter(timeout);
            using (_cts.Token.Register(() => tcs.TrySetCanceled()))
            {
                var recvTask = _udp.ReceiveAsync();
                var done = await Task.WhenAny(recvTask, tcs.Task).ConfigureAwait(false);
                if (done != recvTask) throw new TimeoutException("UDP 接收超时");
                return recvTask.Result.Buffer;
            }
        }
    }

    /// <summary>UDP 广播（设备发现）</summary>
    public Task<int> BroadcastAsync(byte[] data, int port, CancellationToken ct)
        => _udp.SendAsync(data, data.Length, new IPEndPoint(IPAddress.Broadcast, port));

    public void Dispose() { try { _cts?.Cancel(); } catch { } _udp?.Close(); _udp = null; }
}
```

## 5. 断线重连策略（核心）

```csharp
public sealed class ResilientConnection : IDisposable
{
    private readonly Func<CancellationToken, Task<ITransport>> _connectFactory;
    private readonly ILogService _logger;
    private readonly ExponentialBackoff _backoff = new ExponentialBackoff(500, 30000);
    private readonly TimeSpan _healthCheckInterval;
    private ITransport _transport;
    private CancellationTokenSource _cts;
    private Task _supervisor;

    public DeviceState State { get; private set; } = DeviceState.Disconnected;
    public event EventHandler<DeviceState> StateChanged;

    public ResilientConnection(
        Func<CancellationToken, Task<ITransport>> connectFactory,
        ILogService logger,
        TimeSpan? healthCheckInterval = null)
    {
        _connectFactory = connectFactory;
        _logger = logger;
        _healthCheckInterval = healthCheckInterval ?? TimeSpan.FromSeconds(5);
    }

    public void Start(CancellationToken ct)
    {
        _cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        _supervisor = Task.Run(() => SuperviseAsync(_cts.Token));
    }

    private async Task SuperviseAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            // 1) 建连
            if (_transport == null || !_transport.IsOpen)
            {
                SetState(DeviceState.Connecting);
                try
                {
                    _transport = await _connectFactory(ct).ConfigureAwait(false);
                    await _transport.OpenAsync(ct).ConfigureAwait(false);
                    _backoff.Reset();
                    SetState(DeviceState.Connected);
                    _logger.Info($"设备已连接：{_transport.Name}");
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex)
                {
                    SetState(DeviceState.Faulted);
                    int delay = _backoff.NextDelayMs();
                    _logger.Warn($"连接失败，{delay}ms 后重试：{ex.Message}");
                    try { await Task.Delay(delay, ct).ConfigureAwait(false); } catch { break; }
                    continue;
                }
            }

            // 2) 健康检查（心跳 / 探活）
            try
            {
                await Task.Delay(_healthCheckInterval, ct).ConfigureAwait(false);
                if (!await HealthCheckAsync(ct).ConfigureAwait(false))
                {
                    _logger.Warn("健康检查失败，判定连接已失效");
                    throw new IOException("健康检查失败");
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                _logger.Warn($"连接异常，准备重连：{ex.Message}");
                SetState(DeviceState.Reconnecting);
                try { _transport?.Dispose(); } catch { }
                _transport = null;
            }
        }
        SetState(DeviceState.Disconnected);
    }

    /// <summary>子类/注入实现：发心跳包或读一个已知寄存器</summary>
    protected virtual Task<bool> HealthCheckAsync(CancellationToken ct) => Task.FromResult(true);

    private void SetState(DeviceState s)
    {
        if (State == s) return;
        State = s;
        StateChanged?.Invoke(this, s);
    }

    public void Dispose()
    {
        try { _cts?.Cancel(); } catch { }
        try { _supervisor?.Wait(3000); } catch { }
        try { _transport?.Dispose(); } catch { }
        _cts?.Dispose();
    }
}
```

## 6. TCP 踩坑清单

| 坑 | 现象 | 解法 |
|---|---|---|
| 未关 Nagle | 小报文固定 40ms 延迟 | `NoDelay = true` |
| 未开 KeepAlive | 网线拔出后 socket 仍显示"已连接" | `SetSocketOption(KeepAlive)` + 应用层心跳 |
| `Connected` 属性 | 不可靠，反映的是上次操作状态 | 用 `Poll()` + 应用层心跳判定 |
| 大量 TIME_WAIT | 频繁短连接耗尽端口 | 复用长连接；服务端设 `ReuseAddress` |
| 未设超时 | 读卡死，界面无响应 | `ReceiveTimeout` + `CancellationToken` |
| 半包读取 | 帧解析错位 | 累积缓冲 + 拆帧器循环提取 |
| 客户端断开未清理 | 连接泄漏、句柄耗尽 | `finally` 中移除字典 + Close |
| 大数据未分片 | 单次 Write 阻塞 | 分片写，每片 ≤64KB |
| 重连风暴 | 断网时所有设备同时重连打爆网络 | 指数退避 + 随机抖动 |
| 未设置 `_client.ReceiveBufferSize` | 高速数据流丢包 | 按吞吐量设置（如 1MB） |
| IPv6/IPv4 混用 | 连接失败 | 显式解析并指定地址族，工控现场统一用 IPv4 |

## 7. TCP/UDP 核对项

- [ ] 设备是 TCP 客户端还是服务端？谁主动连谁？
- [ ] IP 是固定还是 DHCP？是否有设备发现机制（UDP 广播 / mDNS）？
- [ ] 端口号、最大连接数是否确认？
- [ ] 是否有应用层心跳？周期与超时阈值多少？
- [ ] 帧边界如何界定（长度字段 / 分隔符 / 固定长度）？
- [ ] 断线重连策略是否定义？重连后是否需要重新初始化（登录、握手、订阅）？
- [ ] 是否需要 Nagle 关闭、KeepAlive、接收缓冲调优？
- [ ] 防火墙/端口是否已开放（现场最常见的"连不上"原因）？
- [ ] 网络质量如何？是否需要容忍丢包与乱序？
- [ ] 是否存在多网卡（有线 + WiFi + 虚拟机网卡）干扰？是否需要绑定源 IP？
