---
name: csharp-hmi-development
description: C# 上位机（HMI/SCADA/测试台/工控软件）从需求到交付的全流程开发方法论与可复用资产库。当用户提到上位机、工控软件、HMI、SCADA、WinForms 工控程序、设备通信软件、测试台软件、数据采集软件、C# 串口/TCP/Modbus/OPC UA 通信、PLC 通信、仪器仪表控制、下位机联调、电气核对表、上下位机协议对接，或需要编写 C# 软件需求/设计文档、WinForms 异步多线程与泛型架构时，必须使用本技能。也用于把上位机项目经验沉淀成规范文档、核对表与提示词库。
agent_created: true
---

# C# 上位机软件开发方法论

## 技能定位

本技能把"C# 上位机软件开发"从个人经验变成可执行的工程流程。核心目标是：**任何一个新的上位机项目，套用本技能即可在 30 分钟内建立规范的项目骨架、开发文档体系、核对表与提示词上下文，并在每一轮对话后自动保存进度。**

适用场景：工控上位机、SCADA、数据采集系统、测试台架软件、仪器仪表控制软件、产线 MES 客户端、设备调试工具。

默认技术栈（除非用户明确指定其他）：**WinForms + .NET Framework 4.8 + C# 7.3**，工业现场存量设备兼容性最好。

## ⚡ 5 分钟快速启动

**新项目 3 问快速定位：**

```
┌─────────────────────────────────────────────────────────────┐
│ 问题 1：是独立程序还是平台插件？                              │
├─────────────────────────────────────────────────────────────┤
│ ✓ 独立程序 → 跳转到「判定交付形态 A」                        │
│ ✓ 平台插件 → 先读 references/platform-vsionplat.md          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 问题 2：通信方式是什么？                                      │
├─────────────────────────────────────────────────────────────┤
│ ✓ 串口 RS232/RS485 → references/comm-serial.md              │
│ ✓ TCP/UDP 网络通信 → references/comm-tcp.md                 │
│ ✓ Modbus RTU/TCP → references/comm-modbus.md                │
│ ✓ OPC UA → references/comm-opcua.md                         │
│ ✓ 西门子 S7 → references/comm-s7.md                         │
│ ✓ CAN/CANopen → references/comm-can.md                      │
│ ✓ 未知/自定义 → references/new-device-integration.md        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 问题 3：有没有特殊硬件/协议？                                 │
├─────────────────────────────────────────────────────────────┤
│ ✓ 有 → 先填 assets/checklists/01-hardware-and-electrical.md │
│ ✓ 没有 → 直接运行 scripts/init_project_docs.py 建档         │
└─────────────────────────────────────────────────────────────┘
```

**快速决策规则：**
- 出现"宿主平台""插件""IServiceLogic"等关键词 → 形态 B（平台插件）
- 提到"独立运行""exe 程序""自己做登录" → 形态 A（独立程序）
- 硬件参数不明确（寄存器地址、字节序未知）→ 先填硬件核对表，**禁止猜测**
- 协议文档齐全 → 直接进入阶段 0 建档

## 第一步：判定交付形态（决定后续走哪条路）

接到任务**先做这个判断，再进入工作流**：

| 形态 | 特征 | 走哪份文档 |
|---|---|---|
| **A. 独立上位机程序** | 自己写主窗体、自己启动、自己做登录/日志/权限 | 走 `architecture-winforms.md` 全流程（默认路径） |
| **B. 宿主平台插件** | 目标是 `IndustryPlatBase.dll` 宿主（捷思特 VisionPlat 等），交付物是类库 DLL，被平台加载 | **先读 `references/platform-vsionplat.md`**，本技能其余文档按该文件的"降级使用"表取用 |

判定 B 的信号：出现"宿主平台""插件""类库""`IServiceLogic`""`HardwareLib`""`Logics` 目录""捷思特""VisionPlat""平台已经提供了 XX"等描述。

> **形态 B 的核心纪律**：平台已提供的能力（日志、权限、多语言、串口、TCP 重连、图表、参数 IO、插件管理）**一律不得重复实现**。动手写基础设施前先翻 `platform-vsionplat.md` 第 0 节。

## 核心工作流（五阶段）

接到上位机开发任务时，严格按阶段推进。每个阶段结束 **必须** 执行"进度落盘"（见下节）。

### 阶段 0 — 项目建档（Project Bootstrap）

首个对话轮次必做：

1. 在项目根目录创建 `docs/` 目录与开发文档骨架。
2. 运行 `scripts/init_project_docs.py <项目名> <输出目录>` 生成：
   - `docs/00-软件需求规格说明书.md`
   - `docs/01-系统设计说明书.md`
   - `docs/02-接口与通信协议说明书.md`
   - `docs/03-电气与仪器核对表.md`
   - `docs/04-测试与验收方案.md`
   - `docs/05-开发进度日志.md`
   - `docs/06-问题与风险台账.md`
3. 向用户确认：设备清单、通信方式、采样率、界面规模、交付形态、现场环境约束。

### 阶段 1 — 需求与硬件摸底

- 逐项填写 `00-软件需求规格说明书.md`，用 `assets/checklists/` 下的核对表逐条向用户确认。
- 硬件不确定项一律标记 `⚠️待确认`，**不允许凭猜测进入编码**。
- 通信协议必须先拿到：寄存器地址表 / 报文格式 / 字节序 / 校验方式 / 超时与重试约定。
- 参考 `references/requirements-elicitation.md` 的提问清单。

### 阶段 2 — 架构设计

- 按 `references/architecture-winforms.md` 建立分层架构与项目结构。
- 选定通信抽象：所有设备走 `ITransport` → `IDeviceProtocol` → `IDeviceDriver` 三层泛型抽象。
- 定义线程模型与数据流（采集线程 → 环形缓冲 → 处理管道 → UI 封送）。参考 `references/async-threading.md`。
- 设计完成后写入 `01-系统设计说明书.md`，并画模块图与关键时序图（Mermaid）。

### 阶段 3 — 编码实现

- 通信层直接取用 `references/comm-serial.md`、`comm-tcp.md`、`comm-modbus.md`、`comm-opcua.md`、`comm-s7.md`、`comm-can.md` 中的生产级骨架代码。
- **新设备/新协议接入**：参考 `references/new-device-integration.md` 的 SOP，从协议解析到泛型抽象映射的完整流程。
- 遵守 `references/coding-standards.md`：命名、异常、日志、资源释放、禁用项清单。
- 泛型与可测试性要求见 `references/generics-and-design.md`。
- **遇到问题时**：先查 `references/troubleshooting.md` 速查表，快速定位性能/通信/UI/内存等常见问题。
- 每完成一个模块，立即更新 `05-开发进度日志.md`。

### 阶段 4 — 联调与验收

- 按 `04-测试与验收方案.md` 执行：单机自测 → 打桩联调 → 真实设备联调 → 长稳测试。
- 用 `assets/checklists/` 全量过一遍核对表，未通过项写入 `06-问题与风险台账.md`。
- **长稳测试要求**：连续运行 ≥ 72 小时，内存增长 < 5%，无句柄泄漏。
- **长稳测试执行**：运行 `scripts/long_run_monitor.py` 自动监控进程内存/句柄/CPU，72 小时后生成报告。
- **验收测试脚本**：参考 `assets/checklists/acceptance-test-script.md`，执行模拟数据注入与边界测试。

### 阶段 5 — 交付与知识沉淀

- 输出安装包、操作手册、通信协议文件、源版本与固件版本对照表。
- 把本项目新增的坑、协议变体、客户特殊要求，反哺回本技能的 `references/` 或新建 `assets/` 模板。

## 进度落盘机制（强制）

**这是本技能最重要的约定，不可跳过。**

每当完成一个有实质产出的对话轮次，必须：

1. 用 Edit 工具向 `docs/05-开发进度日志.md` **追加**（不覆盖）一条记录：

```markdown
## [YYYY-MM-DD HH:mm] 轮次标题

- **本次目标**：
- **完成内容**：
- **产出文件**：
- **关键决策及理由**：
- **遗留问题 / 下一步**：
```

2. 若本轮产生了架构决策、协议约定、客户特殊要求等长期有效信息，同步写入项目根目录 `.workbuddy/memory/MEMORY.md`。
3. 若本轮修改了需求或接口，同步更新对应文档章节，并在进度日志中标注"已同步 00/01/02 文档"。

禁止只写"已完成"，必须写清"完成了什么、在哪、依据是什么"。

## 资源索引

### references/ — 规范与方法论（按需加载）

| 文件 | 用途 |
|---|---|
| `platform-vsionplat.md` | **宿主平台插件开发规范**（捷思特 VisionPlat / IndustryPlatBase）。平台已提供能力清单、`IServiceLogic` 7 方法、HardwareLib 两段式结构、平台 API 实测签名速查、14 条平台坑、版本不一致陷阱 |
| `architecture-winforms.md` | WinForms 分层架构、项目结构、依赖注入、配置管理（形态 A 用；形态 B 降级） |
| `async-threading.md` | 异步多线程、UI 封送、CancellationToken、并发集合、定时采集 |
| `generics-and-design.md` | 泛型抽象设计、接口分层、可测试性、设计模式应用 |
| `coding-standards.md` | C# 编码规范、异常处理、日志、资源释放、禁用项 |
| `comm-serial.md` | 串口 / RS232 / RS485 收发骨架、粘包处理、超时重传 |
| `comm-tcp.md` | TCP / UDP 客户端与服务端、心跳、断线重连、长连接保活 |
| `comm-modbus.md` | Modbus RTU / TCP，功能码、寄存器映射、批量读取优化 |
| `comm-opcua.md` | OPC UA 订阅与读写、会话管理、证书 |
| `comm-s7.md` | 西门子 S7 通信（S7.Net 等）、DB 块读写 |
| `comm-can.md` | CAN / CANopen 收发、报文解析 |
| `ui-design-winforms.md` | 工控 UI 设计规范、实时曲线、报警面板、无闪烁刷新 |
| `data-storage.md` | 数据存储、SQLite/SQL Server、批量写入、数据库增长控制 |
| `requirements-elicitation.md` | 需求挖掘提问清单、硬件摸底问题库 |
| `deployment.md` | 部署、安装包、现场升级、远程运维 |
| `performance-tuning.md` | 性能优化、采样率瓶颈定位、GC 调优 |
| `troubleshooting.md` | **常见问题速查表**：性能问题、通信问题、UI 卡顿、内存泄漏的诊断方法与解决模式 |
| `new-device-integration.md` | **新设备接入 SOP**：协议解析、最小验证、泛型抽象映射、测试用例、文档沉淀 |
| `multi-device-orchestration.md` | **多设备并发采集**：设备池管理、采样调度、数据汇聚与时间戳对齐 |
| `deployment-enhanced.md` | **现场部署与运维增强**：环境自检、远程诊断工具包、降级预案 |
| `security-and-permission.md` | **安全与权限**：用户权限分级、操作日志审计、参数保护 |
| `data-analysis-reporting.md` | **数据分析与报表**：数据聚合、报表模板、趋势分析 |

### assets/checklists/ — 核对表（用户要求重点）

| 文件 | 用途 |
|---|---|
| `00-master-checklist.md` | 主核对表汇总（10 大类，逐条可勾选） |
| `01-hardware-and-electrical.md` | 硬件与电气核对表 |
| `02-communication-protocol.md` | 通信协议与寄存器核对表 |
| `03-safety-and-protection.md` | 电气安全与异常保护核对表 |
| `04-instrument-and-product.md` | 仪器仪表及产品核对表 |
| `05-delivery-and-acceptance.md` | 交付与验收核对表 |
| `06-traceability.md` | 版本与追溯核对表 |
| `acceptance-test-script.md` | **验收测试脚本模板**：模拟数据注入、边界测试用例、自动化测试流程 |

### assets/prompts/ — 提示词库

| 文件 | 用途 |
|---|---|
| `csharp-hmi-prompt-library.md` | 分阶段 C# 上位机开发提示词（需求/架构/编码/调试/验收） |
| `code-review-prompt.md` | 上位机代码评审提示词 |

### assets/templates/ — 项目模板

| 文件 | 用途 |
|---|---|
| `project-tree.md` | 标准解决方案目录结构 |
| `device-driver-template.cs` | 新设备驱动接入模板 |
| `progress-log-template.md` | 进度日志模板 |

### scripts/

| 脚本 | 用途 |
|---|---|
| `init_project_docs.py` | 一键生成开发文档骨架（阶段 0） |
| `append_progress.py` | 追加进度日志（进度落盘机制的命令行封装） |
| `long_run_monitor.py` | **长稳测试监控工具**：自动监控进程内存/句柄/CPU，72 小时后生成报告 |

## 使用纪律

0. **先判形态再动手**。是独立程序还是宿主平台插件？形态判断错了，后面所有代码都要重写。宿主平台插件一律先读 `platform-vsionplat.md`。
1. **不猜硬件**。寄存器地址、字节序、电平、供电电压未知时，一律标记待确认并向用户询问。
2. **不跳过文档**。即使客户只要代码，也要先落 `00` 与 `02` 两份文档；这两份是后续所有返工争议的锚点。
3. **不猜平台 API**。宿主平台的编码手册与随附 DLL 经常版本不一致。**以 `.xml` 文档 + 实际编译报错为准**，不用手册签名直接下笔。
4. **通信层必须先通后快**。先实现能连通的最小闭环，再做批量优化与并发提升。
5. **UI 线程只做渲染**。任何阻塞调用（读串口、查数据库、算大数组）一律移出 UI 线程。
6. **现场可维护性优先于代码优雅**。上位机软件在现场往往由非本公司人员维护，日志、自检、参数外置、异常自恢复的权重高于设计模式纯度。
7. **复用优先**。新项目先检索本技能 references 已有骨架，禁止从零手写通信层；在宿主平台上还要先检索平台是否已提供该能力。
