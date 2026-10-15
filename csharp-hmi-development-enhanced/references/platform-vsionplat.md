# VsionPlat / 捷思特 宿主平台插件开发规范

> **适用前提**：目标平台是捷思特 VisionPlat（程序集 `IndustryPlatBase.dll`）。
> 此时**不是**开发独立 WinForms 程序，而是开发两类**类库插件**：
> 1. **业务逻辑插件（ServiceLogic）** —— 实现 `IServiceLogic`，由平台动态加载并显示在主界面。
> 2. **硬件驱动插件（HardwareLib）** —— 实现 `IHardwareInterface`，由平台统一管理与寻址。
>
> 本文件优先级高于 `architecture-winforms.md`。凡是"平台已提供"的能力，**禁止重复实现**。

---

## 0. 平台已提供能力清单（红线：不要重做）

| 能力 | 平台类 | 结论 |
|---|---|---|
| 日志 | `LogFunc` | ❌ 不要引 NLog/log4net |
| 用户/角色/权限 | `UserFunc` | ❌ 不要自己写登录、权限树 |
| 多语言 | `LanguageFunc` | ❌ 不要自己写资源文件切换 |
| 串口 | `SerialProtFunc` | ❌ 不要用 SerialPort 重新封装 |
| TCP 客户端（含断线自动重连） | `TcpClientFunc` / `TcpClientDevice` | ❌ 不要用裸 TcpClient 重写重连逻辑 |
| 硬件驱动框架 | `HardwareFunc` + `IHardwareInterface` | ❌ 不要自己实现设备管理器 |
| 参数/文件 IO 与序列化 | `FileParamHelp` / `FileOperateHelp` | ❌ 不要另引 Json 序列化封装 |
| 曲线/图表控件 | `CustomerControl` | ❌ 不要引第三方图表库（除非平台控件确实不满足） |
| 硬盘写入管理（写入时机排队、定时清理） | `HardDiskFunc` | ❌ 不要自己写定时删除 |
| 插件管理与全局值共享 | `ModuleRuleFunc` | ❌ 不要自己写插件加载器 |

**判断准则**：动手写任何"基础设施"代码前，先在 `IndustryPlatBase.dll` 里搜一遍是否有对应类。平台已做的，你做的每一行都是负债。

---

## 1. 插件形态一：业务逻辑插件（ServiceLogic）

### 1.1 必须实现的接口 `IServiceLogic`（7 个方法）

> ⚠️ **注意版本陷阱**：从 `IndustryPlatBase.xml` 只能看到 3 个方法（`ServiceLogicInit` / `GetServiceLogicDispForm` / `GetServiceLogicInfo`），因为其余 4 个没有 XML 注释。**以官方编码手册 + 实际编译报错为准，共 7 个。**

```csharp
public interface IServiceLogic
{
    // 1. 初始化，path = 本插件参数文件夹路径
    Error ServiceLogicInit(string path);

    // 2. 设置"设备连接状态显示"委托：平台把刷新连接状态灯的方法传给你
    void SetDispEquipmentLinkAction(Action<string, int> action);

    // 3. 设置"软件启动/停止状态"委托
    void SetSoftStartStatus(Action<SoftStaus> action);

    // 4. 设置"是否接受自动启停控制"的标志位
    void SetAutoSoftRunStatusFlag(Action<bool> action);

    // 5. 主界面启动按钮按下事件，返回回调方法
    Func<SoftStaus, bool> SetMainStratEvent();

    // 6. 返回显示在主界面上的业务窗口
    Control GetServiceLogicDispForm();

    // 7. 输出业务逻辑的名称与版本
    void GetServiceLogicInfo(out ServiceLogicInfo info);
}
```

### 1.2 骨架实现（照抄这份）

```csharp
using System;
using System.Windows.Forms;

namespace ServiceLogic
{
    /// <summary>业务逻辑入口。命名空间必须为 ServiceLogic，类名随项目（如 SeviceControl）。</summary>
    public class SeviceControl : IServiceLogic
    {
        // —— 平台注入的委托（不要自己 new，平台会回填）——
        private Action<string, int> _dispLinkAction;
        private Action<SoftStaus> _setSoftStatus;
        private Action<bool> _setAutoRunFlag;

        // —— 插件自述信息（必须在 GetServiceLogicInfo 里填）——
        public string SeviceName { get; } = "6054 老化测试";
        public string SeviceVer  { get; } = "1.0.0.0";

        // 参数文件夹路径，由 ServiceLogicInit 注入，后续所有参数文件都基于它拼路径
        public string DirPath { get; private set; }

        private FrmMain _mainForm;

        #region 1. 初始化

        public Error ServiceLogicInit(string path)
        {
            var ret = new Error();
            try
            {
                DirPath = path;

                // step 1：初始化本插件用到的平台模块 —— 每个平台模块都必须 ModuleInit(path)
                LogFunc.ModuleInit(path);
                UserFunc.ModuleInit(path);
                LanguageFunc.ModuleInit(path);
                HardDiskFunc.ModuleInit(path);
                ModuleRuleFunc.ModuleInit(path);
                // 用到哪个初始化哪个；没用到的不要初始化

                // step 2：向平台权限树注册本插件的权限节点
                //   保证"操作员/管理员"能在平台权限界面上勾选到
                UserFunc.AddToAmountTree("6054老化", "启动");
                UserFunc.AddToAmountTree("6054老化", "停止");
                UserFunc.AddToAmountTree("6054老化", "参数设置");

                // step 3：加载硬件驱动（见第 2 节）
                LoadDriver();

                // step 4：加载型号参数
                LoadModeParam(path);

                // step 5：构造并缓存主界面（不要在这里 Show）
                _mainForm = new FrmMain(this);

                LogFunc.RecordLog(LogType.RunLog, SeviceName, "插件初始化完成");
            }
            catch (Exception ex)
            {
                ret.IsError = true;
                ret.ErrorInfo = "插件初始化失败：" + ex.Message;
                LogFunc.RecordLog(LogType.ErrorLog, SeviceName, ret.ErrorInfo);
            }
            return ret;
        }

        #endregion

        #region 2. 平台委托注册（平台调用这几个方法把回调塞进来）

        public void SetDispEquipmentLinkAction(Action<string, int> action) => _dispLinkAction = action;
        public void SetSoftStartStatus(Action<SoftStaus> action)            => _setSoftStatus   = action;
        public void SetAutoSoftRunStatusFlag(Action<bool> action)           => _setAutoRunFlag  = action;

        #endregion

        #region 3. 启停入口

        /// <summary>平台主界面"启动"按钮按下 → 平台调用本方法拿回调 → 再回调。</summary>
        public Func<SoftStaus, bool> SetMainStratEvent()
        {
            return OnSoftStartStop;
        }

        /// <summary>
        /// 唯一的启停处理入口。所有启动/停止路径（主界面按钮、自动启停、界面内按钮）
        /// 必须收敛到这一个方法，禁止散落多处。
        /// </summary>
        private bool OnSoftStartStop(SoftStaus status)
        {
            try
            {
                // 权限校验交给平台
                if (!UserFunc.CheckPermission("6054老化", status == SoftStaus.Start ? "启动" : "停止"))
                {
                    LogFunc.RecordLog(LogType.SetLog, SeviceName, "当前用户无此操作权限", true);
                    return false;
                }

                if (status == SoftStaus.Start) StartWorkflow();
                else                           StopWorkflow();

                return true;
            }
            catch (Exception ex)
            {
                LogFunc.RecordLog(LogType.ErrorLog, SeviceName, "启停异常：" + ex, true);
                return false;
            }
        }

        #endregion

        #region 4. 平台要求的展示

        public Control GetServiceLogicDispForm()
        {
            if (_mainForm == null) _mainForm = new FrmMain(this);
            return _mainForm;   // 必须返回 Control，平台负责塞进主界面
        }

        public void GetServiceLogicInfo(out ServiceLogicInfo info)
        {
            info = new ServiceLogicInfo
            {
                ServiceLogicName = SeviceName,
                SeviceLogicVer  = SeviceVer      // ⚠️ 注意平台拼写是 SeviceLogicVer，不是 ServiceLogicVer
            };
        }

        #endregion
    }
}
```

### 1.3 插件铁律

1. **命名空间固定为 `ServiceLogic`**，程序集输出到平台的 `Logics\` 目录。
2. `ServiceLogicInit` **不能抛异常**，必须返回 `Error` 结构；平台靠它判断插件是否加载成功。
3. `GetServiceLogicDispForm()` 返回的 `Control` 是平台主界面上的一个子区域 —— **不要在里面再嵌 `Form`**，也不要自己调 `Show()`。
4. 启停入口收敛为**唯一一个方法**（示例中的 `OnSoftStartStop`），供 `SetMainStratEvent`、界面按钮、自动启停共用。多入口是上位机最常见的事故源。
5. 平台委托（`_dispLinkAction` / `_setSoftStatus`）**可能为 null**（某些平台版本不注入），调用前判空。
6. 卸载时释放硬件、停线程、关定时器，见 `ServiceLogicDispose`。

---

## 2. 插件形态二：硬件驱动插件（HardwareLib）

### 2.1 两段式结构：`ProcessModule` + `Driver`

平台的硬件插件是**两层**：`ProcessModule` 是给平台看的门面，`Driver` 是真正干活的。

```csharp
namespace ModbusTCP
{
    /// <summary>平台硬件门面。平台通过反射发现本类。</summary>
    public class ProcessModule
    {
        // ——— 平台生命周期（必须全部实现，平台会逐个调用）———
        public void HardwareInit(string path) { /* 读参数、建 Driver 对象 */ }
        public string GetHardwareName() { return "ModbusTCP设备"; }
        public string GetHardwareVer()  { return "1.0.0.0"; }
        public void GetHardwareInfo(out HardwareInfo info) { /* 名称/型号/版本/说明 */ }
        public void GetHardwareLinkStatus(out List<EquipmentLinkInfo> linkInfos) { /* 连接状态，用于主界面状态灯 */ }
        public void DisplaySetConfig() { /* 弹出平台统一的参数设置窗口 */ }
        public void HardwareDispose() { /* 释放连接 */ }

        // ——— 平台可选：参数读写（供平台参数界面统一调用）———
        public string ReadRomValue(string key) { }
        public void   WriteRomValue(string key, string value) { }
        public string GetAllDriverName() { }

        // ——— 业务方法：用你自定义的强类型封装 ———
        public PowerREG1K070FuncReturn SetSingleVoltageCurrent(PowerREG1K070FuncParam p) { }
    }
}
```

### 2.2 命名与编译约定

| 项 | 约定 |
|---|---|
| 程序集名 | 与 `namespace` 一致（如 `HardwareLib/ModbusTCP.dll` → `namespace ModbusTCP`） |
| 输出目录 | 平台的 `HardwareLib\` 目录 |
| 依赖库 | 私有依赖（EasyModbus / HslCommunication / EPPlus 等）随 DLL 一起放在 `HardwareLib\` 或 `Logics\` |
| 禁止 | 在驱动里直接弹 `MessageBox`；驱动错误一律通过 `HardwareLinkStatus` + `LogFunc` 上报 |

### 2.3 强类型业务方法优于字符串参数

平台老代码喜欢 `string` 进出（如 `SetSingleVoltageCurrent(string)`），**新写的驱动一律同时提供强类型重载**：

```csharp
// ❌ 老写法：调用方拼字符串，运行期才知道参数错
public string SetSingleVoltageCurrent(string cmd);

// ✅ 新写法：编译期检查 + 可读
public PowerREG1K070FuncReturn SetSingleVoltageCurrent(PowerREG1K070FuncParam param);
```

参数类用 `FileParamHelp.SerializeWrite<T>` 落盘，直接获得平台统一的参数文件管理。

---

## 3. 平台 API 速查（实测签名）

> 以下从 `IndustryPlatBase.xml` 与官方编码手册实测提取。
> ⚠️ 手册中 `HardDiskFunc`、`ModuleRuleFunc` 的部分方法在随附 DLL 中**不存在**，以 XML / 实际编译为准。

### 3.1 `LogFunc` — 日志

```csharp
LogFunc.ModuleInit(string path);
void LogFunc.RecordLog(LogType type, string source, string Info, bool dispMessageBox = false);
void LogFunc.RecordCPlusLog(string source, string Info);   // C++ 侧日志
void LogFunc.ShowParamFrm();                               // 平台日志查看界面
void LogFunc.Close();
// enum LogType { RunLog, SetLog, ErrorLog }
```

**约定**：`source` 传 `SeviceName`（本插件名），便于平台按来源过滤。
`dispMessageBox = true` 只在**需要操作员立刻知晓**的场景用（参数写失败、安全联锁触发）；常规日志一律 `false`，否则弹框淹没现场。

### 3.2 `UserFunc` — 用户与权限

```csharp
UserFunc.ModuleInit(string path);
UserFunc.AddToAmountTree(string nodeName, string branchName);   // 注册权限节点（Init 时调）
bool  UserFunc.CheckPermission(string nodeName, string branchName);
Error UserFunc.UserLogin();                                     // 离线登录
Error UserFunc.UserLogin(string userName, string roleName, int time);  // time=秒，0=不注销
void  UserFunc.UserLoginOut();
void  UserFunc.AddLoginChangeFunc(Action action);

// 字段
UserFunc.Level     // UserLevel 枚举：未登录=0, 用户=1, 管理员=2
UserFunc.UserName
UserFunc.RoleName
UserFunc.LoginTime // DateTime
```

**约定**：危险操作（下装程序、改控制地址、清数据）必须 `CheckPermission` 后再执行。**不要自己实现权限判断**。

### 3.3 `SerialProtFunc` / `TcpClientFunc` — 通信（平台已封装，优先使用）

```csharp
// 两者形状基本一致
void SerialProtFunc.ModuleInit(string path);
void SerialProtFunc.WriteParam();                                  // 弹出串口设置界面
List<string> SerialProtFunc.GetAllPortName();
bool SerialProtFunc.GetPortLinkStatus(string portName);
void SerialProtFunc.PortSend(string portName, List<byte> data);
void SerialProtFunc.PortSend(string portName, string data);
void SerialProtFunc.PortSendWithRec(string portName, List<byte> send, out List<byte> recv);
void SerialProtFunc.DisplaySetConfig();
void SerialProtFunc.HardwareDispose();

// TCP 额外提供
void TcpClientFunc.GetRecData(string name, out List<byte> data);
void TcpClientFunc.ParseCanData(...);
bool TcpClientFunc.JudgBitForByte(byte b, int bitIndex);
short TcpClientFunc.GetShortBelongBit(bool[] bits);
```

`TcpClientDevice`（TCP 客户端设备实体，含**平台级自动重连**）：

```csharp
public bool   autoConnectFlag;   // 是否自动重连
public int    timeSpan;          // 重连间隔 ms
public int    times;             // 重连次数
public int    step;              // 状态机步进：-1 / 0 / 1 / 2 / 3
public bool   ConnectFlag;
public Queue<...> RecDataQueue;  // 接收队列
```

**关键结论**：断线重连、粘包接收队列平台已经做了。**你的驱动只需要"发什么、收到什么怎么解析"**。
若平台封装不满足（如需 Modbus 事务级超时），再用 `references/comm-modbus.md` 的裸实现，但**不要两套并存**。

### 3.4 `HardwareFunc` — 硬件管理

```csharp
void HardwareFunc.ModuleInit(string path, string dir, List<string> dlls);
Control HardwareFunc.GetHardwareViewFunc(string name, out HardwareInfo info);
List<string> HardwareFunc.GetAllHardwareName();
void HardwareFunc.GetAllHardwareNameAndVer(out List<string> names, out List<string> vers);
void HardwareFunc.GetAllHardwareLinkStatus(out List<EquipmentLinkInfo> infos);
void HardwareFunc.DispHardwareConfig(string name);
void HardwareFunc.ModuleDispose();
```

### 3.5 `FileParamHelp` / `FileOperateHelp` — 参数与文件

```csharp
// FileParamHelp
Error FileParamHelp.WriteCSV(string filePath, string data, string head);
Error FileParamHelp.ReadCSV(string filePath, out List<string> data);
Error FileParamHelp.SerializeWrite<T>(string filePath, T Data);
Error FileParamHelp.DeserializeRead<T>(string filePath, out T Data);
Error FileParamHelp.XmlSerializeWrite<T>(string filePath, T Data);
Error FileParamHelp.XmlDeserializeRead<T>(string filePath, out T Data);
Error FileParamHelp.JsonSerializeWrite<T>(string filePath, T Data);
Error FileParamHelp.JsonDeserializeRead<T>(string filePath, out T Data);

// FileOperateHelp（节选）
void   FileOperateHelp.CreatDirectory(string filePath);
bool   FileOperateHelp.JudgeFileStatus(string filePath);          // true = 被占用
Error  FileOperateHelp.SelectDirectoryPath(out string dir);
Error  FileOperateHelp.FileCopy(string src, string dstDir, bool cover = true);
Error  FileOperateHelp.DirectoryCopy(string src, string dst, bool cover = true);
Error  FileOperateHelp.SearchingAllSubdirectory(string dir, out List<string> names);
T      FileOperateHelp.JsonDeserializeObj<T>(string json);
string FileOperateHelp.JsonSerializeObj<T>(T data);
```

**注意**：手册里写的是 `class FileParamHelp` / `class ParamFileHelp`，两者混用 —— **以编译为准**，先用 `FileParamHelp`，报错再试另一个。

### 3.6 `BaseGlobal` — 全局路径

```csharp
BaseGlobal.SoftFlag
BaseGlobal.Ver
BaseGlobal.SystemPath        // 系统设置目录
BaseGlobal.ProductPath       // 产品/型号目录（手册写 ModePath ❌）
BaseGlobal.AllLogicPath      // 全部业务逻辑目录（手册写 ModulePath ❌）
BaseGlobal.SamplePath        // 示例目录
BaseGlobal.HardwareDllPath   // 硬件 DLL 目录
BaseGlobal.ToolDllPath       // 工具 DLL 目录
BaseGlobal.ChangeMainSize(...)
```

⚠️ **版本陷阱**：手册中的 `BaseGlobal.ModePath` / `ModulePath` **在 DLL 中不存在**，实际为 `ProductPath` / `AllLogicPath`。
**纪律**：所有路径一律从 `BaseGlobal` / `ServiceLogicInit(path)` 取，**禁止硬编码绝对路径**。

### 3.7 `ModuleRuleFunc` — 插件间通信

```csharp
void ModuleRuleFunc.ModuleInit(string path);
void ModuleRuleFunc.ModuleDispose();
void ModuleRuleFunc.AddGlobalValue(string name);
Error ModuleRuleFunc.GetGlobalValue(string name, out object buff);
Error ModuleRuleFunc.ChangeGlobalValue(string name, object val);
void ModuleRuleFunc.AddModuleFunc(string name, ModuleAction action);
Error ModuleRuleFunc.GetModuleFunc(string name, out ModuleAction action);
List<ModuleInfo> ModuleRuleFunc.GetAllModuleInfo();
```

**用途**：插件之间**不要互相 `Add Reference`**，通过 `ModuleRuleFunc` 的全局值 / 模块方法解耦。

### 3.8 `LanguageFunc` — 多语言

```csharp
void LanguageFunc.ModuleInit(string path);
Error LanguageFunc.GetFormLanguageData(ref FrmUseWrod data);  // 窗口编号需提前放入 data
void LanguageFunc.ShowParamFrm();
void LanguageFunc.SetChangeLanguageAction(Action action);     // 切语言时平台回调
void LanguageFunc.RunChangeAction();
```

**约定**：所有界面文字必须走 `LanguageFunc`，**禁止硬编码中文字符串**。
每新增一个窗口，必须在 `GetFormLanguageData` 里登记窗口编号，否则该窗口切换语言无效。

---

## 4. 平台插件开发的高频坑

| # | 坑 | 后果 | 正确做法 |
|---|---|---|---|
| 1 | 拿手册签名直接编码 | 编译报错（手册与 DLL 版本不一致） | 以 `.xml` + 编译报错为准；存疑先写最小探针类试编译 |
| 2 | 忘记 `XXXFunc.ModuleInit(path)` | 该模块功能全部失效/静默不工作 | 用到的平台模块**逐个**初始化，集中放在 `ServiceLogicInit` 开头 |
| 3 | 在 `ServiceLogicInit` 里 `Show()` 窗口 | 主界面错乱、模态卡死 | 只构造不显示，交给 `GetServiceLogicDispForm()` |
| 4 | 启停逻辑散落在多个按钮事件里 | 状态机错乱、重复启动、设备双击 | 收敛为唯一入口方法 |
| 5 | 自己写串口/TCP/日志/权限 | 重复劳动 + 与平台行为不一致 + 现场两套日志 | 一律用平台类 |
| 6 | 硬编码绝对路径 | 换机器/换型号直接崩 | 用 `ServiceLogicInit(path)` + `BaseGlobal.*` |
| 7 | 驱动里弹 `MessageBox` | 无人值守时卡死产线 | 错误走 `LogFunc.RecordLog` + 连接状态上报 |
| 8 | 未注册权限节点 | 权限界面上根本看不到这一项 | 有可操作功能的都必须 `AddToAmountTree` |
| 9 | 界面文字硬编码 | 切语言后仍显示中文 | 全部走 `LanguageFunc` |
| 10 | 插件间直接引用程序集 | 一个插件升级，全平台重编译 | 走 `ModuleRuleFunc` 全局值/方法 |
| 11 | 忘记实现 `HardwareDispose` / `ServiceLogicDispose` | 句柄泄漏、重新加载失败 | 停线程、关连接、注销事件 |
| 12 | 把平台注入的委托当非空 | `NullReferenceException` | 调用前判空，并给出降级路径 |
| 13 | 数据类型选错（Modbus 寄存器映射到 `short` 还是 `ushort`） | 数值翻负数、量程不对 | 在 `02-接口与通信协议说明书.md` 里明确写出有符号/无符号与量纲 |
| 14 | 旧项目的控制地址（如 `D180`/`D182`/`D1074`）被新项目复用 | 程序下错地址，撞坏设备 | 每项目建立**独立寄存器基线类**（如 `PlcRegisterMap6054`），并在 XML 注释里写明"禁止再写旧地址" |

---

## 5. 与本技能其他文档的关系

| 本技能文档 | 在平台插件模式下如何使用 |
|---|---|
| `architecture-winforms.md` | **降级使用**。分层思想仍有效，但"程序入口 / DI 容器 / 主窗体 / 配置引导"由平台负责，跳过这些章节 |
| `async-threading.md` | **完整适用**。平台不给线程模型，采集线程、环形缓冲、UI 封送仍需自己做 |
| `coding-standards.md` | **完整适用** |
| `comm-serial.md` / `comm-tcp.md` | **降级为参考**。优先用 `SerialProtFunc` / `TcpClientFunc`；平台不满足时再取骨架，且不可两套并用 |
| `comm-modbus.md` / `comm-opcua.md` / `comm-s7.md` / `comm-can.md` | **完整适用**。这就是写在 `HardwareLib` 插件里的东西 |
| `ui-design-winforms.md` | **部分适用**。颜色/字体/防闪烁/写参数二次确认全部适用；但曲线优先用 `CustomerControl` |
| `data-storage.md` | **部分适用**。文件写入排队与清理优先用 `HardDiskFunc`；数据库仍按本文档做 |
| `deployment.md` | **降级使用**。部署形态是"拷贝 DLL 到 `Logics\` / `HardwareLib\`"，不是做安装包 |

---

## 6. 平台插件项目文档要求

沿用 `references/dev-docs.md` 的 7 文档体系，但**新增/强化两份**：

1. `docs/02-接口与通信协议说明书.md` 增补一节 **"平台交互接口"**，至少写清：
   - 本插件实现了 `IServiceLogic` 还是 `IHardwareInterface`（或两者）
   - 注册的权限节点全表（nodeName / branchName / 用途）
   - 使用的平台模块清单（哪些 `XXXFunc.ModuleInit`）
   - 依赖的平台 DLL 与版本号
   - 参数文件夹结构（相对 `ServiceLogicInit(path)` 的路径）
2. `docs/07-寄存器地址基线.md`（新项目必建）
   - 每个 PLC 寄存器一行：地址 / 类型 / 有无符号 / 量纲 / 换算系数 / 读写权限 / 来源依据
   - 头部必须写明依据文件（如"依据 6054PLC地址表.xlsx"）与**禁止复用的历史地址黑名单**

---

## 7. 新插件启动检查单（每接一个平台项目先过一遍）

- [ ] 确认插件形态：ServiceLogic / HardwareLib / 两者都要
- [ ] 拿到 `IndustryPlatBase.dll` **及其 `.xml`**（不是只有手册）
- [ ] 确认平台版本号，并核实手册与 DLL 是否一致（抽查 3 个方法签名）
- [ ] 列出本次要用到的平台模块，确认每个都调了 `ModuleInit(path)`
- [ ] 列出要注册的权限节点
- [ ] 确认参数文件夹路径来源（`ServiceLogicInit` 的 `path`）
- [ ] 建立寄存器地址基线文档 `07-寄存器地址基线.md`
- [ ] 确认所有依赖 DLL 的放置目录与版本
- [ ] 确认卸载路径（`HardwareDispose` / `ServiceLogicDispose`）已实现
- [ ] 确认启停入口唯一
