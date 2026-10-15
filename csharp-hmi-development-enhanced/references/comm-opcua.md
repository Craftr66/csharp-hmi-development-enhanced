# OPC UA 实现规范

## 1. 选型与依赖

| 库 | 类型 | 适用 |
|---|---|---|
| `OPCFoundation.NetStandard.Opc.Ua.Client` | 官方 | **推荐**，功能最全 |
| `Workstation.UaClient` | 第三方 | API 更友好，封装度更高 |
| `Opc.UaFx.Client` | 商业 | 授权费用，支持好 |

.NET Framework 4.8 建议使用 `OPCFoundation.NetStandard.Opc.Ua.*` 系列（有 net462 目标）。

```xml
<PackageReference Include="OPCFoundation.NetStandard.Opc.Ua.Client" Version="1.4.371.86" />
<PackageReference Include="OPCFoundation.NetStandard.Opc.Ua.Configuration" Version="1.4.371.86" />
```

## 2. 核心概念速查

| 概念 | 说明 | 上位机关注点 |
|---|---|---|
| Endpoint | 服务端点 `opc.tcp://ip:4840` | SecurityPolicy 必须匹配 |
| Session | 会话 | 有超时，需保活 |
| Subscription | 订阅 | **推荐方式**，服务器主动推送 |
| MonitoredItem | 监控项 | 绑定 NodeId，可设采样间隔与死区 |
| NodeId | 节点标识 | `ns=2;s=Device.Tag` 或 `ns=2;i=1234` |
| SecurityPolicy | 安全策略 | None / Basic256Sha256 等 |
| PublishingInterval | 发布周期 | 最小通常 100ms |

**核心决策：优先用 Subscription（订阅）而非轮询。** OPC UA 的设计意图就是服务器推送，轮询会浪费带宽且延迟高。

## 3. 会话管理实现

```csharp
using Opc.Ua;
using Opc.Ua.Client;
using Opc.Ua.Configuration;
using System;
using System.Threading;
using System.Threading.Tasks;

public sealed class OpcUaSessionManager : IDisposable
{
    private readonly OpcUaConfig _cfg;
    private readonly ILogService _logger;
    private ApplicationConfiguration _appConfig;
    private Session _session;
    private readonly SemaphoreSlim _sessionLock = new SemaphoreSlim(1, 1);

    public bool IsConnected => _session != null && _session.Connected;

    public OpcUaSessionManager(OpcUaConfig cfg, ILogService logger)
    {
        _cfg = cfg;
        _logger = logger;
    }

    public async Task ConnectAsync(CancellationToken ct)
    {
        await _sessionLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (IsConnected) return;

            // 1) 构建应用配置（证书、安全策略）
            _appConfig = await BuildApplicationConfigurationAsync().ConfigureAwait(false);

            // 2) 选择端点
            var endpointDescription = await CoreClientUtils
                .SelectEndpoint(_appConfig, new Uri(_cfg.EndpointUrl), ct)
                .ConfigureAwait(false);

            if (!endpointDescription.SecurityPolicyUri.Contains(_cfg.SecurityPolicy))
            {
                var all = await CoreClientUtils.GetEndpoints(_appConfig, new Uri(_cfg.EndpointUrl), ct)
                                               .ConfigureAwait(false);
                endpointDescription = all.FirstOrDefault(e =>
                    e.SecurityPolicyUri.Contains(_cfg.SecurityPolicy))
                    ?? throw new InvalidOperationException(
                        $"服务器不支持安全策略 {_cfg.SecurityPolicy}");
            }

            var endpointConfiguration = EndpointConfiguration.Create(_appConfig);
            var endpoint = new ConfiguredEndpoint(null, endpointDescription, endpointConfiguration);

            // 3) 创建会话
            _session = await Session.Create(
                _appConfig,
                endpoint,
                updateBeforeConnect: false,
                sessionName: $"HMI-{Environment.MachineName}",
                sessionTimeout: (uint)_cfg.SessionTimeoutMs,
                identity: BuildIdentity(),
                preferredLocales: null,
                ct: ct).ConfigureAwait(false);

            // 4) 关键：订阅保活与断线事件
            _session.KeepAlive += OnKeepAlive;
            _session.SessionClosing += OnSessionClosing;

            _logger.Info($"OPC UA 已连接：{_cfg.EndpointUrl}，策略={endpointDescription.SecurityPolicyUri}");
        }
        finally { _sessionLock.Release(); }
    }

    private async Task<ApplicationConfiguration> BuildApplicationConfigurationAsync()
    {
        var app = new ApplicationInstance
        {
            ApplicationName = "HmiOpcUaClient",
            ApplicationType = ApplicationType.Client,
            ConfigSectionName = "HmiOpcUaClient"
        };

        var config = new ApplicationConfiguration
        {
            ApplicationName = "HmiOpcUaClient",
            ApplicationUri = Utils.Format("urn:{0}:HmiOpcUaClient", Utils.GetHostName()),
            ApplicationType = ApplicationType.Client,
            SecurityConfiguration = new SecurityConfiguration
            {
                ApplicationCertificate = new CertificateIdentifier
                {
                    StoreType = "Directory",
                    StorePath = _cfg.CertificateStorePath,     // 如 "%CommonApplicationData%\\OPC Foundation\\CertificateStores\\MachineDefault"
                    SubjectName = "CN=HmiOpcUaClient, O=YourCompany"
                },
                TrustedPeerCertificates = new CertificateTrustList
                {
                    StoreType = "Directory",
                    StorePath = _cfg.TrustedPeerStorePath
                },
                TrustedIssuerCertificates = new CertificateTrustList
                {
                    StoreType = "Directory",
                    StorePath = _cfg.TrustedIssuerStorePath
                },
                RejectedCertificateStore = new CertificateTrustList
                {
                    StoreType = "Directory",
                    StorePath = _cfg.RejectedStorePath
                },
                AutoAcceptUntrustedCertificates = false,      // ⚠️ 生产环境必须 false
                AddAppCertToTrustedStore = true
            },
            TransportConfigurations = new TransportConfigurationCollection(),
            TransportQuotas = new TransportQuotas
            {
                OperationTimeout = 15000,
                MaxStringLength = 1_048_576,
                MaxByteStringLength = 4_194_304,
                MaxArrayLength = 65_535,
                MaxMessageSize = 4_194_304,
                MaxBufferSize = 65_535,
                ChannelLifetime = 300_000,
                SecurityTokenLifetime = 3_600_000
            },
            ClientConfiguration = new ClientConfiguration
            {
                DefaultSessionTimeout = _cfg.SessionTimeoutMs,
                MinSubscriptionLifetime = 10_000
            }
        };

        // 证书不存在时自动创建自签名证书
        bool certOk = await app.CheckApplicationInstanceCertificates(false, 0, ct: default)
                                 .ConfigureAwait(false);
        if (!certOk) throw new InvalidOperationException("OPC UA 应用证书创建失败");

        await config.Validate(ApplicationType.Client).ConfigureAwait(false);
        return config;
    }

    private IUserIdentity BuildIdentity()
    {
        switch (_cfg.AuthMode)
        {
            case OpcAuthMode.Anonymous:
                return new UserIdentity(new AnonymousIdentityToken());
            case OpcAuthMode.UserName:
                return new UserIdentity(_cfg.UserName, _cfg.Password);
            case OpcAuthMode.Certificate:
                return new UserIdentity(_cfg.ClientCertificate);
            default:
                return new UserIdentity(new AnonymousIdentityToken());
        }
    }

    private void OnKeepAlive(Session session, KeepAliveEventArgs e)
    {
        if (ServiceResult.IsBad(e.Status))
        {
            _logger.Warn($"OPC UA 保活异常：{e.Status}，将触发重连");
            // 会话内部会自动重连，但需应用层感知
            ConnectionLost?.Invoke(this, EventArgs.Empty);
        }
    }

    private void OnSessionClosing(object sender, EventArgs e)
        => _logger.Warn("OPC UA 会话被关闭");

    public event EventHandler ConnectionLost;

    public void Dispose()
    {
        try
        {
            if (_session != null)
            {
                _session.KeepAlive -= OnKeepAlive;
                _session.SessionClosing -= OnSessionClosing;
                _session.Close(5000);
                _session.Dispose();
            }
        }
        catch (Exception ex) { _logger?.Warn($"关闭 OPC UA 会话异常：{ex.Message}"); }
        finally { _sessionLock.Dispose(); }
    }
}
```

## 4. 订阅（推荐方式）

```csharp
public sealed class OpcUaSubscription : IDisposable
{
    private readonly Session _session;
    private readonly ILogService _logger;
    private Subscription _subscription;
    private readonly Dictionary<uint, string> _handleToTag = new Dictionary<uint, string>();
    private uint _nextClientHandle = 1;

    public event EventHandler<TagValueChangedEventArgs<double>> ValueChanged;

    public void Create(int publishingIntervalMs, IEnumerable<OpcTagDefinition> tags)
    {
        _subscription = new Subscription(_session.DefaultSubscription)
        {
            PublishingInterval = publishingIntervalMs,
            KeepAliveCount = 30,              // 30 × interval 无变化后发保活
            LifetimeCount = 90,               // 90 × interval 无 ack 则订阅失效
            MaxNotificationsPerPublish = 5000,
            PublishingEnabled = true,
            Priority = 0
        };
        _session.AddSubscription(_subscription);
        _subscription.Create();

        foreach (var tag in tags)
        {
            var item = new MonitoredItem(_subscription.DefaultItem)
            {
                DisplayName = tag.Name,
                StartNodeId = new NodeId(tag.NodeId),
                AttributeId = Attributes.Value,
                MonitoringMode = tag.Mode == OpcMonitorMode.ReportAlways
                    ? MonitoringMode.Reporting
                    : MonitoringMode.Reporting,
                SamplingInterval = tag.SamplingIntervalMs,
                QueueSize = tag.QueueSize,                  // 0 = 只保留最新
                DiscardOldest = true,
                ClientHandle = _nextClientHandle++
            };

            // 死区过滤：变化小于死区不上报，大幅降低通信量
            if (tag.Deadband > 0)
            {
                item.Filter = new DataChangeFilter
                {
                    Trigger = DataChangeTrigger.StatusValue,
                    DeadbandType = (uint)DeadbandType.Absolute,
                    DeadbandValue = tag.Deadband
                };
            }

            item.Notification += OnItemNotification;
            _subscription.AddItem(item);
            _handleToTag[item.ClientHandle] = tag.Name;
        }

        _subscription.ApplyChanges();

        // ⚠️ 必须检查创建结果，否则静默失败
        var bad = _subscription.MonitoredItems
            .Where(i => ServiceResult.IsBad(i.Status.Error))
            .ToList();
        if (bad.Count > 0)
        {
            foreach (var i in bad)
                _logger.Error($"OPC UA 监控项 {i.DisplayName} 创建失败：{i.Status.Error}");
            throw new ProtocolException($"{bad.Count} 个监控项创建失败");
        }

        _logger.Info($"OPC UA 订阅已建立：{_subscription.MonitoredItemCount} 个监控项，周期 {publishingIntervalMs}ms");
    }

    private void OnItemNotification(MonitoredItem item, MonitoredItemNotificationEventArgs e)
    {
        foreach (var value in item.DequeueValues())
        {
            if (ServiceResult.IsBad(value.StatusCode))
            {
                _logger.Warn($"OPC UA 项 {item.DisplayName} 状态异常：{value.StatusCode}");
                continue;
            }

            double v = Convert.ToDouble(value.Value ?? 0);
            // 携带质量码与时间戳，工业场景必须保留
            ValueChanged?.Invoke(this, new TagValueChangedEventArgs<double>(
                _handleToTag.TryGetValue(item.ClientHandle, out var n) ? n : item.DisplayName,
                v,
                DateTime.UtcNow,
                value.StatusCode.Code));
        }
    }

    public void Dispose()
    {
        try
        {
            if (_subscription != null)
            {
                _subscription.Delete(true);
                _session.RemoveSubscription(_subscription);
                _subscription.Dispose();
            }
        }
        catch (Exception ex) { _logger?.Warn($"删除订阅异常：{ex.Message}"); }
    }
}
```

## 5. 批量读写

```csharp
public async Task<IReadOnlyDictionary<string, double>> ReadBatchAsync(
    IEnumerable<string> nodeIds, CancellationToken ct)
{
    var nodes = nodeIds.Select(id => new ReadValueId
    {
        NodeId = new NodeId(id),
        AttributeId = Attributes.Value
    }).ToList();

    // 分批：单次请求节点数建议 ≤ 1000，且注意 MaxMessageSize
    const int batchSize = 500;
    var result = new Dictionary<string, double>();

    for (int i = 0; i < nodes.Count; i += batchSize)
    {
        ct.ThrowIfCancellationRequested();
        var chunk = nodes.Skip(i).Take(batchSize).ToList();

        var response = await _session.ReadAsync(
            null, 0, TimestampsToReturn.Both, chunk, ct).ConfigureAwait(false);

        for (int j = 0; j < chunk.Count; j++)
        {
            var dv = response.Results[j];
            if (ServiceResult.IsBad(dv.StatusCode))
            {
                _logger.Warn($"读取 {chunk[j].NodeId} 失败：{dv.StatusCode}");
                continue;
            }
            result[chunk[j].NodeId.ToString()] = Convert.ToDouble(dv.Value ?? 0);
        }
    }
    return result;
}

public async Task WriteBatchAsync(
    IReadOnlyDictionary<string, double> values, CancellationToken ct)
{
    var nodes = values.Select(kv => new WriteValue
    {
        NodeId = new NodeId(kv.Key),
        AttributeId = Attributes.Value,
        Value = new DataValue(new Variant(kv.Value))
    }).ToList();

    var response = await _session.WriteAsync(null, nodes, ct).ConfigureAwait(false);

    for (int i = 0; i < nodes.Count; i++)
    {
        if (ServiceResult.IsBad(response.Results[i]))
            throw new ProtocolException($"写入 {nodes[i].NodeId} 失败：{response.Results[i]}");
    }
}
```

## 6. 浏览节点（辅助配置工具用）

```csharp
public async Task DumpNodeTreeAsync(string rootNodeId, string outputFile, CancellationToken ct)
{
    // 用于生成标签清单，方便配置标签时对照
    var toBrowse = new BrowseDescriptionCollection
    {
        new BrowseDescription
        {
            NodeId = new NodeId(rootNodeId),
            BrowseDirection = BrowseDirection.Forward,
            ReferenceTypeId = ReferenceTypeIds.HierarchicalReferences,
            IncludeSubtypes = true,
            NodeClassMask = (uint)(NodeClass.Object | NodeClass.Variable),
            ResultMask = (uint)BrowseResultMask.All
        }
    };

    var response = await _session.BrowseAsync(null, null, 0,
        toBrowse, ct).ConfigureAwait(false);

    using (var sw = new StreamWriter(outputFile, false, Encoding.UTF8))
    {
        foreach (var refDesc in response.Results[0].References)
        {
            sw.WriteLine($"{refDesc.NodeId}\t{refDesc.BrowseName}\t{refDesc.DisplayName}");
        }
    }
}
```

## 7. 证书管理（现场高频问题）

```csharp
public static class OpcCertificateHelper
{
    /// <summary>把服务器证书加入信任列表（首次连接被拒绝时使用）</summary>
    public static void TrustCertificate(string rejectedStorePath, string trustedStorePath,
                                        string thumbprint, ILogService logger)
    {
        using (var rejected = new CertificateStoreIdentifier(rejectedStorePath).OpenStore())
        using (var trusted = new CertificateStoreIdentifier(trustedStorePath).OpenStore())
        {
            var cert = rejected.Enumerate()
                .FirstOrDefault(c => c.Thumbprint.Equals(thumbprint, StringComparison.OrdinalIgnoreCase));
            if (cert == null) { logger.Warn($"未在拒绝列表找到证书 {thumbprint}"); return; }

            trusted.Add(cert);
            rejected.Remove(cert);
            logger.Info($"已信任证书：{cert.Subject}");
        }
    }
}
```

**现场情况**：首次连接通常会被服务器拒绝（证书未信任）。上位机应提供"证书管理"界面，让现场人员能看到拒绝列表并一键信任，而不是让工程师去翻文件夹。

## 8. OPC UA 踩坑清单

| 坑 | 现象 | 解法 |
|---|---|---|
| 证书未信任 | 连接被拒 `BadCertificateUntrusted` | 提供证书信任界面 |
| 安全策略不匹配 | 无法建立会话 | 枚举端点并匹配支持的策略 |
| 会话超时未保活 | 隔夜后连接失效 | 订阅 KeepAlive，设置合理 SessionTimeout |
| 用轮询代替订阅 | 延迟高、服务器压力大 | 用 Subscription |
| 未设死区 | 高频噪声导致通信量爆炸 | 设 DataChangeFilter 死区 |
| 未检查 MonitoredItem 创建结果 | 静默少读数据 | 检查 Status.Error 并抛异常 |
| QueueSize 太小 | 高速变化时丢数据（只留最新） | 按需增大 QueueSize 并 DiscardOldest=false |
| 忽略 StatusCode | 读到的是坏值当成好值用 | 必须检查 `ServiceResult.IsBad` |
| NodeId 命名空间搞错 | 读到别的节点 | 用浏览工具导出节点树核对 |
| 单次读写节点过多 | 报文超限被截断 | 分批（≤500） |
| 服务器 PublishingInterval 限制 | 设的周期不生效 | 读取服务器最小周期后取较大值 |
| 自动接受不可信证书 | 安全漏洞 | 生产环境必须 `AutoAcceptUntrustedCertificates = false` |

## 9. OPC UA 核对项

- [ ] 端点 URL、端口（默认 4840）是否确认？
- [ ] 安全策略与安全模式是什么（None / Sign / SignAndEncrypt）？
- [ ] 身份验证方式：匿名 / 用户名密码 / 证书？
- [ ] 证书存储路径与格式（DER / PFX）？
- [ ] 需要采集的节点 NodeId 清单是否已导出？
- [ ] 采用订阅还是轮询？发布周期多少？
- [ ] 每个标签的采样间隔与死区如何设置？
- [ ] 服务器是否限制最大订阅数、最大监控项数？
- [ ] 是否需要写入？写权限如何控制？
- [ ] 断线重连后订阅是否自动恢复？还是需重建？
- [ ] 服务器最小发布周期是多少？
- [ ] 是否有质量码（Quality）需要展示与告警？
