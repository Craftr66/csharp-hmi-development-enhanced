# 标准解决方案目录结构模板

```
SolutionName/
├── SolutionName.sln
├── .gitignore
├── .gitattributes
├── README.md
├── docs/                                    # 开发文档（本技能强制）
│   ├── 00-软件需求规格说明书.md
│   ├── 01-系统设计说明书.md
│   ├── 02-接口与通信协议说明书.md
│   ├── 03-电气与仪器核对表.md
│   ├── 04-测试与验收方案.md
│   ├── 05-开发进度日志.md
│   └── 06-问题与风险台账.md
│
├── build/
│   ├── Version.props                        # 统一版本号
│   ├── installer/                           # Inno Setup 脚本
│   │   └── setup.iss
│   └── prereq/                              # 前置依赖安装包
│
├── config/                                  # 配置模板（随安装包发布）
│   ├── appsettings.json
│   ├── appsettings.local.json.template
│   └── nlog.config
│
├── src/
│   ├── SolutionName.UI/                     # WinForms 主程序
│   │   ├── SolutionName.UI.csproj
│   │   ├── Program.cs                       # 入口 + 全局异常兜底
│   │   ├── Bootstrap.cs                     # 组合根（DI 容器）
│   │   ├── App.config
│   │   ├── Forms/
│   │   │   ├── MainForm.cs
│   │   │   ├── MainForm.Designer.cs
│   │   │   ├── MainForm.resx
│   │   │   ├── SettingsForm.cs
│   │   │   └── AboutForm.cs
│   │   ├── Controls/                        # 自绘控件
│   │   │   ├── ValueLabel.cs
│   │   │   ├── StatusIndicator.cs
│   │   │   ├── RealtimeChart.cs
│   │   │   └── AlarmPanel.cs
│   │   ├── ViewModels/
│   │   │   ├── MainViewModel.cs
│   │   │   └── SettingsViewModel.cs
│   │   ├── Infrastructure/
│   │   │   ├── ControlExtensions.cs         # SafeInvoke
│   │   │   ├── ExceptionHandler.cs
│   │   │   └── HmiTheme.cs                  # 颜色/字体
│   │   └── Resources/
│   │       ├── Strings.resx
│   │       └── Strings.en.resx
│   │
│   ├── SolutionName.App/                    # 应用服务层
│   │   ├── SolutionName.App.csproj
│   │   ├── Acquisition/
│   │   │   ├── IAcquisitionService.cs
│   │   │   └── AcquisitionService.cs
│   │   ├── Alarming/
│   │   │   ├── IAlarmService.cs
│   │   │   └── AlarmService.cs
│   │   ├── Commands/
│   │   │   ├── ICommandService.cs
│   │   │   └── CommandService.cs
│   │   └── Reporting/
│   │       └── ReportService.cs
│   │
│   ├── SolutionName.Domain/                 # 领域层（零外部依赖）
│   │   ├── SolutionName.Domain.csproj
│   │   ├── Entities/
│   │   │   ├── Sample.cs
│   │   │   ├── TagDefinition.cs
│   │   │   └── AlarmItem.cs
│   │   ├── Enums/
│   │   │   ├── DeviceState.cs
│   │   │   ├── TagAccess.cs
│   │   │   └── AlarmLevel.cs
│   │   ├── ValueObjects/
│   │   │   ├── TagAddress.cs
│   │   │   └── DeadbandFilter.cs
│   │   └── Services/                        # 纯算法，可单测
│   │       ├── ModbusAddress.cs
│   │       ├── ModbusConvert.cs
│   │       └── DeviceStateMachine.cs
│   │
│   ├── SolutionName.Comm/                   # 通信基础设施
│   │   ├── SolutionName.Comm.csproj
│   │   ├── Abstractions/
│   │   │   ├── ITransport.cs
│   │   │   ├── IDeviceProtocol.cs
│   │   │   ├── IDeviceDriver.cs
│   │   │   ├── TransportDataEventArgs.cs
│   │   │   ├── ProtocolResponse.cs
│   │   │   └── Exceptions.cs
│   │   ├── Serial/
│   │   │   ├── SerialTransport.cs
│   │   │   ├── SerialConfig.cs
│   │   │   ├── FrameDelimiterParser.cs
│   │   │   └── ComPortResolver.cs
│   │   ├── Tcp/
│   │   │   ├── TcpClientTransport.cs
│   │   │   ├── TcpServerTransport.cs
│   │   │   ├── TcpReceiveLoop.cs
│   │   │   └── UdpTransport.cs
│   │   ├── Modbus/
│   │   │   ├── ModbusRtuProtocol.cs
│   │   │   ├── ModbusTcpProtocol.cs
│   │   │   ├── ModbusPollPlanner.cs
│   │   │   ├── ModbusConvert.cs
│   │   │   └── ModbusWriteGuard.cs
│   │   ├── OpcUa/
│   │   │   ├── OpcUaSessionManager.cs
│   │   │   └── OpcUaSubscription.cs
│   │   ├── S7/
│   │   │   ├── S7PlcDriver.cs
│   │   │   ├── S7BlockReader.cs
│   │   │   └── S7ValueParser.cs
│   │   ├── Can/
│   │   │   ├── ICanChannel.cs
│   │   │   ├── ZlgCanChannel.cs
│   │   │   ├── CanopenPdoParser.cs
│   │   │   ├── CanopenSdoClient.cs
│   │   │   └── CanopenNmtMaster.cs
│   │   ├── Simulation/
│   │   │   └── SimulatedTransport.cs        # 无硬件开发
│   │   ├── DeviceManager.cs                 # 设备生命周期托管
│   │   ├── ResilientConnection.cs           # 重连监督
│   │   └── ExponentialBackoff.cs
│   │
│   ├── SolutionName.Storage/                # 数据持久化
│   │   ├── SolutionName.Storage.csproj
│   │   ├── Sqlite/
│   │   │   ├── SqliteFactory.cs
│   │   │   └── SqliteRepository.cs
│   │   ├── BulkWritePipeline.cs             # 生产者-消费者落库
│   │   ├── DataRetentionService.cs          # 滚动清理
│   │   └── Migration/
│   │       ├── IMigration.cs
│   │       └── MigrationRunner.cs
│   │
│   └── SolutionName.Common/                 # 工具与通用
│       ├── SolutionName.Common.csproj
│       ├── Logging/
│       │   ├── ILogService.cs
│       │   └── NLogService.cs
│       ├── Config/
│       │   ├── IConfigProvider.cs
│       │   └── LayeredConfigProvider.cs
│       ├── Buffers/
│       │   ├── RingBuffer.cs
│       │   └── ObjectPool.cs
│       ├── Diagnostics/
│       │   ├── ResourceMonitor.cs
│       │   └── DiagnosticPackageBuilder.cs
│       └── Extensions/
│           ├── ByteExtensions.cs
│           └── StringExtensions.cs
│
├── tests/
│   ├── SolutionName.Domain.Tests/
│   │   ├── ModbusAddressTests.cs
│   │   └── DeadbandFilterTests.cs
│   ├── SolutionName.Comm.Tests/
│   │   ├── ProtocolParserTests.cs
│   │   └── PollPlannerTests.cs
│   └── SolutionName.App.Tests/
│       └── AcquisitionServiceTests.cs
│
└── tools/
    ├── ProtocolTester/                      # 协议调试工具
    └── DataViewer/                          # 数据查看工具
```

## 关键约定

| 约定 | 说明 |
|---|---|
| 依赖方向 | UI → App → Domain；UI/App/Storage/Comm → Common；**Domain 零依赖** |
| Comm 不引用 WinForms | 保持可单测、可在服务中复用 |
| UI 不直接引用 Storage/Comm 实现 | 只引用接口（通过 App 层） |
| 每个协议一个文件 | 新增协议 = 新增文件，不改已有代码 |
| SimulatedTransport 必须存在 | 无硬件可完整跑通业务 |
| Domain 层 100% 可单测 | 不依赖 IO、日志、配置的具体实现 |

## .gitignore 要点

```gitignore
# 构建产物
[Bb]in/
[Oo]bj/
*.user
*.suo
.vs/

# 现场配置（含敏感信息，不入库）
config/appsettings.local.json
*.local.json

# 运行时数据
logs/
data/
export/
*.db
*.db-wal
*.db-shm

# 诊断包
diag_*.zip

# 备份
backup/
*.bak
```

## Version.props 示例

```xml
<Project>
  <PropertyGroup>
    <Version>1.0.0</Version>
    <AssemblyVersion>1.0.0.0</AssemblyVersion>
    <FileVersion>1.0.0.0</FileVersion>
    <Company>YourCompany</Company>
    <Product>HMI Software</Product>
    <Copyright>Copyright © 2026</Copyright>
    <!-- 构建号由 CI 或脚本注入 -->
  </PropertyGroup>
</Project>
```
