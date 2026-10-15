# 部署与现场交付规范

## 1. 部署形态选择

| 形态 | 适用 | 优点 | 缺点 |
|---|---|---|---|
| Setup 安装包（Inno Setup / NSIS） | 大多数场景 | 规范、可卸载、可带依赖 | 需制作 |
| MSI（WiX） | 需域内批量部署 | 支持组策略推送 | 制作复杂 |
| 绿色免安装（zip） | 现场无管理员权限 | 简单 | 无法注册组件、快捷方式 |
| ClickOnce | 需自动更新 | 内置更新 | 限制多，工控少用 |
| 打包为 Windows 服务 | 无界面采集 | 开机自启、无登录 | 无界面调试难 |

**推荐**：Inno Setup 做 Setup 包 + 可选绿色包。

## 2. 部署前置检查（现场必做）

```
□ 操作系统版本：____________  是否符合要求 ☐
□ .NET Framework 4.8 是否已安装（注册表 HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full\Release ≥ 528040）☐
□ 是否有管理员权限 ☐
□ 硬盘剩余空间：____ GB  是否 ≥ 需求 ☐
□ 串口驱动是否已安装（设备管理器确认）☐
□ USB 转串口的 COM 口号：____
□ 网络是否可达（ping 设备）☐
□ 防火墙是否已开放端口：____ ☐
□ 杀毒软件型号：____  是否已加白名单 ☐
□ 是否有域策略限制 ☐
□ 屏幕分辨率/DPI 缩放：____ ☐
□ 系统时间与时区是否正确 ☐
□ 是否安装 NI-VISA / 仪器驱动（如适用）☐
□ 是否需要安装 CAN 驱动（如适用）☐
```

## 3. 安装包设计

### 3.1 目录结构

```
C:\Program Files\<Company>\<Product>\
├── <Product>.exe
├── *.dll                      主程序依赖
├── libs\                      第三方 DLL（设备驱动、仪器库）
│   ├── ControlCAN.dll
│   └── S7netplus.dll
├── config\
│   ├── appsettings.json       主配置（随安装包提供）
│   ├── appsettings.local.json 现场覆盖（安装时生成空模板）
│   └── nlog.config
├── docs\                      随程序附带的操作手册
├── tools\                     辅助工具（协议测试、诊断）
└── (运行时生成)
    ├── logs\                  日志（可配置到其他盘）
    ├── data\                  数据库
    └── export\                导出文件

D:\HmiData\                    推荐：数据与日志放非系统盘
├── logs\
├── data\
└── backup\
```

**原则**：程序与数据分离。程序在 `Program Files`（只读），数据在独立目录（可写）。

### 3.2 安装脚本要点（Inno Setup 示例）

```pascal
[Setup]
AppName=上位机软件
AppVersion=1.0.0
DefaultDirName={autopf}\Company\Product
DefaultGroupName=Company
OutputBaseFilename=HmiSetup_1.0.0
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "publish\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
Source: "libs\*"; DestDir: "{app}\libs"; Flags: ignoreversion

[Dirs]
; 数据目录放开写权限
Name: "{sd}\HmiData"; Permissions: everyone-modify
Name: "{sd}\HmiData\logs"; Permissions: everyone-modify
Name: "{sd}\HmiData\data"; Permissions: everyone-modify

[Run]
; 安装 .NET Framework（如果缺失）
Filename: "{app}\prereq\ndp48-x86-x64-allos-enu.exe"; \
  Parameters: "/q /norestart"; StatusMsg: "正在安装 .NET Framework 4.8..."; \
  Check: NeedsDotNet48

[Icons]
Name: "{group}\上位机软件"; Filename: "{app}\Product.exe"
Name: "{commondesktop}\上位机软件"; Filename: "{app}\Product.exe"

[Code]
function NeedsDotNet48: Boolean;
var Release: Cardinal;
begin
  Result := not (RegQueryDWordValue(HKLM,
    'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release)
    and (Release >= 528040));
end;
```

**要点**：
- 检测并安装 .NET Framework 4.8（可离线安装包）
- 数据目录权限放开（避免 UAC 问题）
- 保留现场配置（升级时不覆盖 `appsettings.local.json`）

### 3.3 升级安装

```pascal
[Code]
// 升级时保留现场配置与数据
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    if FileExists(ExpandConstant('{app}\config\appsettings.local.json')) then
      FileCopy(ExpandConstant('{app}\config\appsettings.local.json'),
               ExpandConstant('{tmp}\appsettings.local.json.bak'), False);
  if CurStep = ssPostInstall then
    if FileExists(ExpandConstant('{tmp}\appsettings.local.json.bak')) then
      FileCopy(ExpandConstant('{tmp}\appsettings.local.json.bak'),
               ExpandConstant('{app}\config\appsettings.local.json'), False);
end;
```

## 4. 配置管理

### 4.1 分层配置

```
appsettings.json        随安装包发布，包含默认值与注释（用 JSON 注释扩展）
appsettings.local.json  现场文件，优先级更高，升级不覆盖
环境变量                最高优先级（用于临时覆盖）
```

```csharp
public sealed class LayeredConfigProvider : IConfigProvider
{
    private JObject _base;
    private JObject _local;

    public void Load(string baseDir)
    {
        var basePath = Path.Combine(baseDir, "config", "appsettings.json");
        var localPath = Path.Combine(baseDir, "config", "appsettings.local.json");

        _base = LoadWithComments(basePath);
        _local = File.Exists(localPath) ? LoadWithComments(localPath) : new JObject();

        Validate();
    }

    /// <summary>启动时校验配置，失败则拒绝启动（宁可起不来也不要起一半）</summary>
    private void Validate()
    {
        var errors = new List<string>();

        foreach (var dev in GetSection<JArray>("Devices") ?? new JArray())
        {
            var id = dev["Id"]?.ToString();
            if (string.IsNullOrEmpty(id)) errors.Add("存在未配置 Id 的设备");
            if (string.IsNullOrEmpty(dev["Protocol"]?.ToString()))
                errors.Add($"设备 {id} 未配置 Protocol");
            if (string.IsNullOrEmpty(dev["Endpoint"]?.ToString()))
                errors.Add($"设备 {id} 未配置 Endpoint");
        }

        if (errors.Count > 0)
            throw new ConfigException("配置校验失败：\n" + string.Join("\n", errors));
    }

    /// <summary>支持 // 与 /* */ 注释的 JSON 加载</summary>
    private static JObject LoadWithComments(string path)
    {
        var text = File.ReadAllText(path, Encoding.UTF8);
        // 用 JsonTextReader 支持注释
        using (var reader = new JsonTextReader(new StringReader(text))
               { DateParseHandling = DateParseHandling.None })
        {
            return JObject.Load(reader);
        }
    }
}
```

### 4.2 配置热加载

```csharp
// 用 FileSystemWatcher 监听配置变更
var watcher = new FileSystemWatcher(configDir, "appsettings.local.json")
{
    NotifyFilter = NotifyFilters.LastWrite,
    EnableRaisingEvents = true
};
watcher.Changed += (s, e) =>
{
    // ⚠️ 文件可能正被写入，需延迟并重试
    Task.Delay(500).ContinueWith(_ =>
    {
        try
        {
            _configProvider.Reload();
            _logger.Info("配置已热加载");
            ConfigChanged?.Invoke(this, EventArgs.Empty);
        }
        catch (Exception ex)
        {
            _logger.Error(ex, "配置热加载失败，继续使用旧配置");
        }
    });
};
```

**注意**：并非所有配置都能热加载。通信参数变更需重建设备连接；界面参数可直接生效。文档中要明确哪些可热加载。

## 5. 开机自启

| 方式 | 适用 | 说明 |
|---|---|---|
| 启动文件夹快捷方式 | 简单场景 | 需用户登录 |
| 注册表 Run 键 | 简单场景 | 需用户登录 |
| 任务计划程序 | **推荐** | 可设延迟启动、无需登录（配合服务） |
| Windows 服务 | 无界面采集 | 无界面，调试不便 |

**推荐**：任务计划程序，延迟 30 秒启动（等设备与网络就绪）。

```
触发器：系统启动时，延迟 30 秒
操作：启动程序 <安装目录>\Product.exe
条件：取消"只有在计算机使用交流电源时才启动"
设置：如果任务失败，每 1 分钟重启，最多 3 次
```

## 6. 日志与诊断

### 6.1 NLog 配置（现场适用）

```xml
<?xml version="1.0" encoding="utf-8" ?>
<nlog xmlns="http://www.nlog-project.org/schemas/NLog.xsd"
      autoReload="true" throwExceptions="false" internalLogLevel="Off">

  <variable name="logDir" value="${basedir}/../../HmiData/logs" />
  <variable name="layout"
            value="${longdate}|${level:uppercase=true:padding=-5}|${logger:shortName=true:padding=-28}|${message}${onexception:${newline}${exception:format=ToString}}" />

  <targets async="true">
    <!-- 常规日志 -->
    <target xsi:type="File" name="main"
            fileName="${logDir}/hmi-${shortdate}.log"
            layout="${layout}"
            archiveAboveSize="52428800"
            maxArchiveFiles="30"
            keepFileOpen="true"
            encoding="utf-8"
            concurrentWrites="false" />

    <!-- 通信报文日志（默认关闭，排查时打开） -->
    <target xsi:type="File" name="comm"
            fileName="${logDir}/comm-${shortdate}.log"
            layout="${longdate}|${message}"
            archiveAboveSize="104857600"
            maxArchiveFiles="7"
            keepFileOpen="true"
            encoding="utf-8" />

    <!-- 报警独立文件，便于统计 -->
    <target xsi:type="File" name="alarm"
            fileName="${logDir}/alarm-${shortdate}.log"
            layout="${longdate}|${message}"
            maxArchiveFiles="90"
            keepFileOpen="true" />

    <!-- 错误单独一份，便于快速定位 -->
    <target xsi:type="File" name="error"
            fileName="${logDir}/error-${shortdate}.log"
            layout="${layout}"
            maxArchiveFiles="90"
            keepFileOpen="true" />
  </targets>

  <rules>
    <logger name="Comm.Trace" minlevel="Trace" writeTo="comm" enabled="false" />
    <logger name="Alarm" minlevel="Info" writeTo="alarm" />
    <logger name="*" minlevel="Error" writeTo="error" />
    <logger name="*" minlevel="Info" writeTo="main" />
  </rules>
</nlog>
```

**要点**：
- `async="true"`：异步写日志，不阻塞业务线程
- `keepFileOpen`：保持文件打开，避免频繁开关（性能）
- `archiveAboveSize` + `maxArchiveFiles`：自动轮转与清理
- 报文日志单独文件且默认关闭
- `throwExceptions="false"`：日志失败不能影响业务

### 6.2 诊断包导出（现场必备）

```csharp
public sealed class DiagnosticPackageBuilder
{
    /// <summary>一键导出诊断包，便于远程排障</summary>
    public string Build(string outputDir, DeviceManager deviceManager)
    {
        var stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        var zipPath = Path.Combine(outputDir, $"diag_{stamp}.zip");

        // 用临时目录组装
        var tmp = Path.Combine(Path.GetTempPath(), $"diag_{stamp}");
        Directory.CreateDirectory(tmp);

        try
        {
            // 1) 系统信息
            File.WriteAllText(Path.Combine(tmp, "system.txt"), CollectSystemInfo(), Encoding.UTF8);

            // 2) 软件与版本
            File.WriteAllText(Path.Combine(tmp, "version.txt"), CollectVersionInfo(), Encoding.UTF8);

            // 3) 配置（脱敏）
            File.Copy(ConfigPath, Path.Combine(tmp, "config_sanitized.json"), true);
            SanitizeSecrets(Path.Combine(tmp, "config_sanitized.json"));

            // 4) 最近日志（3 天）
            CopyRecentLogs(LogDir, Path.Combine(tmp, "logs"), days: 3);

            // 5) 设备状态快照
            File.WriteAllText(Path.Combine(tmp, "devices.txt"),
                deviceManager.DumpStateSnapshot(), Encoding.UTF8);

            // 6) 数据库结构（不含数据）
            File.WriteAllText(Path.Combine(tmp, "schema.sql"), DumpSchema(), Encoding.UTF8);

            // 7) 序列化崩溃信息（若存在）
            if (File.Exists(CrashFile))
                File.Copy(CrashFile, Path.Combine(tmp, "last_crash.txt"), true);

            // 打包
            if (File.Exists(zipPath)) File.Delete(zipPath);
            ZipFile.CreateFromDirectory(tmp, zipPath);

            return zipPath;
        }
        finally
        {
            try { Directory.Delete(tmp, true); } catch { }
        }
    }

    private string CollectSystemInfo() => $@"
OS: {Environment.OSVersion}
64位系统: {Environment.Is64BitOperatingSystem}
机器名: {Environment.MachineName}
用户名: {Environment.UserName}
CPU核数: {Environment.ProcessorCount}
.NET版本: {Environment.Version}
系统运行时长: {TimeSpan.FromMilliseconds(Environment.TickCount64)}
当前时间: {DateTime.Now:yyyy-MM-dd HH:mm:ss}
时区: {TimeZoneInfo.Local.DisplayName}
";
}
```

**诊断包内容**：系统信息、版本、脱敏配置、最近日志、设备状态快照、数据库结构、崩溃信息。

## 7. 现场常见故障与排查

| 现象 | 常见原因 | 排查步骤 |
|---|---|---|
| 程序无法启动 | .NET 缺失、权限不足、依赖 DLL 缺失 | 看事件查看器、装 .NET、看依赖 |
| 串口打不开 | 端口被占用、驱动未装、端口号变了 | 设备管理器、关闭占用程序、按 VID/PID 找端口 |
| 连不上设备 | IP 错、不在同网段、防火墙、多网卡 | ping、telnet 端口、关防火墙测试 |
| 通信时断时续 | 干扰、终端电阻、线缆、波特率 | 换线、加终端电阻、降波特率测试 |
| 数据全是错值 | 字节序、地址偏移、数据类型 | 用已知值验证、对照手册 |
| 界面卡死 | UI 线程阻塞、数据库锁 | 看日志、看是否有同步 IO |
| 内存持续增长 | 事件泄漏、无界队列 | 诊断包比对、长稳测试 |
| 数据不落库 | 磁盘满、数据库锁、权限 | 看日志、看磁盘、看权限 |
| 报警不响 | 配置阈值、声音设备 | 检查配置、检查音频设备 |
| 报告打不开 | Office 版本、路径权限 | 检查 Office、检查临时目录权限 |

## 8. 远程运维

| 方式 | 说明 | 安全考虑 |
|---|---|---|
| 向日葵 / TeamViewer | 最常用 | 设固定密码、用完退出 |
| Windows 远程桌面 | 系统自带 | 需开端口、限 IP |
| VPN + RDP | 更安全 | 需客户 IT 配合 |
| 自研远程诊断 | 只上传诊断包 | 不开放远程控制 |

**注意**：很多工厂禁止外网，需提前确认。诊断包导出 + 邮件/微信传递是最通用的方案。

## 9. 交付清单

```
交付物
├── 安装包
│   ├── HmiSetup_1.0.0.exe
│   └── prereq/ (ndp48 安装包)
├── 绿色包（可选）
│   └── HmiPortable_1.0.0.zip
├── 文档
│   ├── 操作手册.pdf          （面向操作员，图文步骤）
│   ├── 维护手册.pdf          （面向维护，含故障排查）
│   ├── 安装部署说明.pdf
│   ├── 通信协议说明书.pdf    （双方签字版）
│   ├── 版本说明.txt
│   └── 常见问题FAQ.pdf
├── 源码（如合同包含）
│   ├── 完整 Git 仓库
│   └── 构建说明.md
├── 配置模板
│   ├── appsettings.json
│   └── 现场配置示例
└── 培训材料
    └── 培训PPT.pdf
```

## 10. 部署检查清单

**安装前**：
- [ ] 现场环境勘查完成（见第 2 节）
- [ ] 确认安装包在干净系统测试通过
- [ ] 确认 .NET Framework 安装包已随附
- [ ] 确认设备驱动已准备
- [ ] 确认数据目录规划（非系统盘优先）

**安装中**：
- [ ] 关闭杀毒软件（或加白名单）
- [ ] 以管理员身份运行安装程序
- [ ] 记录安装路径
- [ ] 配置现场参数（IP、串口、路径）

**安装后**：
- [ ] 首次启动完成初始化
- [ ] 逐个设备连接测试
- [ ] 数据采集与落库验证
- [ ] 界面显示与报警验证
- [ ] 开机自启验证
- [ ] 断电重启验证
- [ ] 长稳运行观察（至少 2 小时）
- [ ] 培训并交付手册

**交付确认**：
- [ ] 验收测试用例执行完毕
- [ ] 遗留问题记录并约定
- [ ] 验收报告签字
- [ ] 备份出厂配置与数据库模板
- [ ] 提供技术支持联系方式
