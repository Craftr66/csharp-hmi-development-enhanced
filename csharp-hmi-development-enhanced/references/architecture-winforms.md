# WinForms 上位机架构规范（.NET Framework 4.8）

## 1. 分层架构总则

上位机软件按五层组织，**依赖方向严格单向向下**，禁止反向引用与跨层调用。

```
┌─────────────────────────────────────────────┐
│  UI 层 (WinForms Forms/Controls)            │  只做渲染与用户输入
├─────────────────────────────────────────────┤
│  ViewModel / Presenter 层                   │  状态编排、命令、UI 状态映射
├─────────────────────────────────────────────┤
│  Application / Service 层                   │  业务流程编排、事务边界、任务调度
├─────────────────────────────────────────────┤
│  Domain 层                                  │  实体、值对象、领域规则、算法
├─────────────────────────────────────────────┤
│  Infrastructure 层                          │  通信、存储、日志、文件、外部系统
└─────────────────────────────────────────────┘
```

**关键约束**：

- UI 层 **禁止** 直接 `new SerialPort()`、`new TcpClient()`、`SqlConnection`。一律通过构造函数注入接口。
- Infrastructure **禁止** 引用 `System.Windows.Forms`。若必须触发 UI 更新，通过事件 + 上层封送。
- Domain 层 **零外部依赖**，不引用任何 NuGet 包（保证可单元测试）。

## 2. 标准解决方案结构

```
SolutionName/
├── SolutionName.sln
├── .gitignore
├── docs/                              # 开发文档（本技能强制要求）
├── build/
│   ├── Version.props                  # 统一版本号
│   └── SolutionName.nuspec
├── src/
│   ├── SolutionName.UI/               # WinForms 主程序
│   │   ├── Program.cs
│   │   ├── App.config
│   │   ├── Forms/
│   │   ├── Controls/
│   │   ├── ViewModels/
│   │   └── Resources/
│   ├── SolutionName.App/              # 应用服务层
│   ├── SolutionName.Domain/           # 领域模型
│   ├── SolutionName.Comm/             # 通信基础设施
│   │   ├── Abstractions/              # ITransport / IDeviceProtocol / IDeviceDriver
│   │   ├── Serial/
│   │   ├── Tcp/
│   │   ├── Modbus/
│   │   ├── OpcUa/
│   │   ├── S7/
│   │   └── Can/
│   ├── SolutionName.Storage/          # 数据持久化
│   └── SolutionName.Common/           # 工具、扩展、常量
└── tests/
    ├── SolutionName.Domain.Tests/
    ├── SolutionName.Comm.Tests/
    └── SolutionName.App.Tests/
```

## 3. WinForms 项目的现代工程化配置

.NET Framework 4.8 使用传统 csproj，但必须做以下增强，不要用 20 年前的写法。

### 3.1 C# 语言版本

在 csproj 的 `PropertyGroup` 中启用：

```xml
<PropertyGroup>
  <LangVersion>7.3</LangVersion>
  <TargetFrameworkVersion>v4.8</TargetFrameworkVersion>
  <PlatformTarget>x64</PlatformTarget>
  <TreatWarningsAsErrors>false</TreatWarningsAsErrors>
  <WarningLevel>4</WarningLevel>
  <GenerateAssemblyInfo>true</GenerateAssemblyInfo>
</PropertyGroup>
```

> 说明：.NET Framework 4.8 官方最高支持 C# 7.3。若通过 `Microsoft.Net.Compilers.Toolset` 可上 9.0，但**工业现场不推荐**，会增加部署不确定性。

### 3.2 DPI 与视觉样式

`Program.cs` 必须包含：

```csharp
[STAThread]
static void Main()
{
    Application.EnableVisualStyles();
    Application.SetCompatibleTextRenderingDefault(false);

    // 高 DPI 支持（WinForms 在 .NET Framework 下需手动开启）
    Application.SetHighDpiMode(HighDpiMode.SystemAware); // 需 System.Windows.Forms 4.7+ 或 App.config 方式

    // 全局异常兜底
    Application.ThreadException += (s, e) => ExceptionHandler.Handle(e.Exception, fatal: false);
    AppDomain.CurrentDomain.UnhandledException += (s, e) => ExceptionHandler.Handle(e.ExceptionObject as Exception, fatal: true);
    TaskScheduler.UnobservedTaskException += (s, e) => { ExceptionHandler.Handle(e.Exception, false); e.SetObserved(); };

    // 组合根
    var container = Bootstrap.BuildContainer();
    var mainForm = container.Resolve<MainForm>();
    Application.Run(mainForm);
}
```

`App.config` 中启用 DPI 感知：

```xml
<appSettings>
  <add key="EnableWindowsFormsHighDpiAutoResizing" value="true" />
</appSettings>
<System.Windows.Forms.ApplicationConfigurationSection>
  <add key="DpiAwareness" value="PerMonitorV2" />
</System.Windows.Forms.ApplicationConfigurationSection>
```

### 3.3 NuGet 必备包

| 包 | 用途 | 备注 |
|---|---|---|
| `Microsoft.Extensions.DependencyInjection` | DI 容器 | 4.8 可用，轻量 |
| `NLog` 或 `Serilog` + `Serilog.Sinks.File` | 日志 | 推荐 NLog，配置文件外置 |
| `System.Threading.Tasks.Extensions` | ValueTask | 可选 |
| `System.Buffers` / `System.Memory` | Span/Memory | 用 `System.Memory` 包可在 4.8 用 Span |
| `Newtonsoft.Json` | JSON 配置与协议 | 首选，比 DataContractJsonSerializer 好用 |
| `Microsoft.EntityFrameworkCore.SqlServer` / `System.Data.SQLite` | 数据存储 | 见 data-storage.md |

## 4. 依赖注入与组合根

**禁止** 在业务代码中手写 `new` 去创建有依赖的服务。全部走构造注入。

```csharp
public static class Bootstrap
{
    public static IServiceProvider BuildContainer()
    {
        var services = new ServiceCollection();

        // 配置
        services.AddSingleton<IConfigProvider, JsonConfigProvider>();

        // 日志
        services.AddSingleton<ILogService, NLogService>();

        // 通信
        services.AddSingleton<ITransportFactory, TransportFactory>();
        services.AddSingleton<IDeviceManager, DeviceManager>();

        // 存储
        services.AddSingleton<IRepositoryFactory, RepositoryFactory>();

        // 应用服务
        services.AddSingleton<IAcquisitionService, AcquisitionService>();

        // UI（窗体用 Transient，ViewModel 用 Singleton 或 Scoped）
        services.AddSingleton<MainViewModel>();
        services.AddTransient<MainForm>();

        return services.BuildServiceProvider();
    }
}
```

**WinForms 特有问题**：设计器要求窗体有无参构造函数。解决方案：

```csharp
public partial class MainForm : Form
{
    private readonly MainViewModel _vm;

    // 仅供设计器使用，禁止在运行时代码调用
    public MainForm() { InitializeComponent(); }

    public MainForm(MainViewModel vm) : this()
    {
        _vm = vm;
        BindViewModel();
    }

    protected override void OnLoad(EventArgs e)
    {
        base.OnLoad(e);
        if (DesignMode || LicenseManager.UsageMode == LicenseUsageMode.Designtime) return;
        _vm?.Initialize();
    }
}
```

## 5. 配置管理

**原则：所有现场可变参数必须外置到配置文件，禁止硬编码。**

配置分三层，优先级由低到高：

1. `app.config` / `App.exe.config` — 仅有框架级设置
2. `config/appsettings.json` — 主配置（设备清单、通信参数、采集周期、路径）
3. `config/appsettings.local.json` — 现场覆盖（工位号、IP、串口号），**不进版本库**

```csharp
public interface IConfigProvider
{
    T Get<T>(string key) where T : class, new();
    T GetSection<T>(string sectionName) where T : class, new();
    void Save<T>(string key, T value) where T : class;
    IObservable<ConfigChangedEvent> Changes { get; }   // 支持热加载
}
```

配置示例（`config/appsettings.json`）：

```json
{
  "Devices": [
    {
      "Id": "PLC-01",
      "Name": "主控PLC",
      "Protocol": "ModbusTcp",
      "Endpoint": "192.168.1.10:502",
      "PollIntervalMs": 200,
      "TimeoutMs": 1000,
      "RetryCount": 3,
      "Tags": [
        { "Name": "Speed", "Address": "40001", "Type": "UInt16", "Scale": 0.1, "Unit": "rpm" }
      ]
    }
  ],
  "Acquisition": { "RingBufferCapacity": 100000, "UiRefreshIntervalMs": 100 },
  "Storage": { "Provider": "Sqlite", "ConnectionString": "Data Source=data\\hmi.db" },
  "Logging": { "MinLevel": "Info", "Directory": "logs", "RetainDays": 30 }
}
```

**配置校验**：启动时对配置做一次 Schema 校验，失败则弹出明确错误并拒绝启动（宁可起不来，也不要起一半）。

## 6. 错误处理与容错

三层防线：

1. **设备级**：单个设备通信异常 → 该设备进入 `Faulted` 状态，自动退避重连（指数退避，上限 30s），**不影响其他设备**。
2. **服务级**：采集服务内部 try/catch，记录日志，触发告警，不崩溃。
3. **应用级**：`Application.ThreadException` + `AppDomain.UnhandledException` 兜底，写崩溃日志（含堆栈、版本、设备状态快照），提示用户并允许导出诊断包。

```csharp
public enum DeviceState { Disconnected, Connecting, Connected, Faulted, Reconnecting }
```

**禁止** 用 `catch (Exception) { }` 吞掉异常。至少 `Logger.Error` 并附上下文。

## 7. 生命周期与资源释放

- 所有实现 `IDisposable` 的设备驱动、传输对象，统一由 `DeviceManager` 托管，程序退出时按**逆序**释放。
- 退出流程：`停止采集 → 等待在途任务完成（带超时）→ 断开设备 → 刷盘 → 释放句柄 → 关闭日志`。
- 窗体关闭时若有关键任务未完成，弹确认框，不允许静默退出。
- **禁止** 在 `Dispose` 中抛异常。

## 8. 日志规范

分级：`Trace / Debug / Info / Warn / Error / Fatal`。

**必须记录日志的场景**：

- 程序启动/退出（含版本、机器名、操作系统、配置摘要）
- 设备连接/断开/重连（含端点、耗时、失败原因）
- 配置变更（谁改的、改前改后）
- 通信超时、校验失败、协议异常（含收发原始报文，十六进制）
- 未捕获异常（含完整堆栈）
- 关键用户操作（启动采集、下发参数、导出报表）

**日志格式**（NLog 配置）：

```
${longdate}|${level:uppercase=true:padding=-5}|${logger:shortName=true}|${message}${onexception:${newline}${exception:format=ToString}}
```

日志文件按天滚动，保留 30 天，单文件上限 50MB。**通信报文日志单独一个 appender**，便于现场排查，默认关闭 Trace 级。

## 9. 多语言与现场适配

- 界面文本外置到 `.resx`，至少支持中英文。
- 单位、小数位、时间格式从配置读取，禁止硬编码 `"0.00"`。
- 路径使用相对路径 + `AppDomain.CurrentDomain.BaseDirectory`，**禁止** 硬编码 `D:\` 等盘符。

## 10. 架构评审检查清单

设计阶段完成后逐条自检：

- [ ] 依赖是否严格单向？有无 UI 层直接访问数据库/串口？
- [ ] 所有现场可变参数是否外置？
- [ ] 单设备故障是否隔离，不扩散到全局？
- [ ] 通信层是否抽象到接口，是否可替换、可 Mock？
- [ ] 是否定义了优雅退出流程，有无资源泄漏风险？
- [ ] 是否具备崩溃兜底与诊断包导出？
- [ ] 日志是否覆盖连接、超时、配置变更、异常四类关键事件？
- [ ] 是否可在无真实设备的情况下用模拟器完整跑通业务？（这一点决定开发效率）
