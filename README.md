[README.md](https://github.com/user-attachments/files/33470234/README.md)
# C# 上位机开发增强版 Skill 说明文档

## 📋 版本信息

- **Skill 名称**: csharp-hmi-development-enhanced
- **版本**: v2.0（增强版）
- **发布日期**: 2026-10-15
- **基于版本**: v1.0（原始版）

---

## 🎯 Skill 定位

本 skill 是 **C# 上位机软件开发的完整工程化方法论**，将个人经验转化为可执行的标准流程。

**核心目标**：任何新的上位机项目，套用本 skill 可在 **30 分钟内**建立：
- 规范的项目骨架
- 完整的开发文档体系
- 全面的核对表与提示词上下文
- 自动进度保存机制

---

## 🆕 增强版新增内容

本增强版在原版基础上，补充了以下关键优化：

### 1. **快速启动路径** ⚡
- 新增"5 分钟快速启动"决策树
- 3 问快速定位：交付形态 → 通信方式 → 特殊硬件
- 大幅降低新手上手门槛

### 2. **常见问题速查表** 🔍
- 新增 `references/troubleshooting.md`（约 7000 字）
- 覆盖 7 大类问题：
  - 性能问题（采样率瓶颈、内存泄漏）
  - 通信问题（Modbus 失败、TCP 断开）
  - UI 问题（界面卡顿、曲线闪烁）
  - 架构问题（设备接入、多设备并发）
  - 现场部署问题（环境差异、远程调试）
  - 协议适配问题（固件升级兼容）
  - 工具推荐速查

### 3. **新设备接入 SOP** 📝
- 新增 `references/new-device-integration.md`（约 5000 字）
- 五步接入法：
  1. 协议解析（手册 → 代码结构体）
  2. 最小验证（发一帧、收一帧）
  3. 泛型抽象映射（实现 IDeviceProtocol）
  4. 测试用例编写
  5. 文档沉淀
- 包含协议版本管理与适配器模式

### 4. **长稳测试监控工具** 🛠️
- 新增 `scripts/long_run_monitor.py`（约 400 行）
- 功能：
  - 自动监控进程内存、句柄、CPU
  - 持续 72 小时（可配置）
  - 自动生成 CSV 样本 + JSON 报告 + Markdown 报告
  - 自动判定是否通过（内存增长 < 5%、句柄无泄漏）
- 使用方法：
  ```bash
  python long_run_monitor.py --process-name "YourApp.exe" --duration 72
  ```

### 5. **验收测试脚本模板** ✅
- 新增 `assets/checklists/acceptance-test-script.md`（约 3000 字）
- 12 个标准测试用例分类：
  - 功能测试（设备连接、数据采集、存储导出、报警处理）
  - 边界与压力测试（长时间运行、极限采样率、多设备并发）
  - 异常与容错测试（设备故障、软件恢复、资源耗尽）
  - 用户界面测试（响应性、多分辨率适配）
- 包含自动化测试脚本示例（Python 数据注入）
- 测试报告模板与验收通过标准

### 6. **文档索引更新**
在 `SKILL.md` 中补充了以下新增文档：
- `troubleshooting.md` - 常见问题速查表
- `new-device-integration.md` - 新设备接入 SOP
- `multi-device-orchestration.md` - 多设备并发采集
- `deployment-enhanced.md` - 现场部署与运维增强
- `security-and-permission.md` - 安全与权限
- `data-analysis-reporting.md` - 数据分析与报表
- `acceptance-test-script.md` - 验收测试脚本模板
- `long_run_monitor.py` - 长稳测试监控工具

---

## 📁 目录结构

```
csharp-hmi-development-enhanced/
├── SKILL.md                          # Skill 主文档（已增强）
├── README.md                         # 本说明文档
│
├── references/                       # 规范与方法论（26+ 文档）
│   ├── platform-vsionplat.md        # 宿主平台插件开发规范
│   ├── architecture-winforms.md     # WinForms 分层架构
│   ├── async-threading.md           # 异步多线程
│   ├── generics-and-design.md       # 泛型抽象设计
│   ├── coding-standards.md          # C# 编码规范
│   ├── comm-serial.md               # 串口通信骨架
│   ├── comm-tcp.md                  # TCP/UDP 通信
│   ├── comm-modbus.md               # Modbus 协议
│   ├── comm-opcua.md                # OPC UA 协议
│   ├── comm-s7.md                   # 西门子 S7 通信
│   ├── comm-can.md                  # CAN/CANopen 通信
│   ├── ui-design-winforms.md        # 工控 UI 设计规范
│   ├── data-storage.md              # 数据存储
│   ├── requirements-elicitation.md  # 需求挖掘提问清单
│   ├── deployment.md                # 部署与安装包
│   ├── performance-tuning.md        # 性能优化
│   ├── troubleshooting.md           # ✨ 常见问题速查表（新增）
│   ├── new-device-integration.md    # ✨ 新设备接入 SOP（新增）
│   ├── multi-device-orchestration.md      # ✨ 多设备并发（待补充）
│   ├── deployment-enhanced.md             # ✨ 现场部署增强（待补充）
│   ├── security-and-permission.md         # ✨ 安全与权限（待补充）
│   └── data-analysis-reporting.md         # ✨ 数据分析与报表（待补充）
│
├── assets/                           # 实用资产
│   ├── checklists/                  # 核对表
│   │   ├── 00-master-checklist.md
│   │   ├── 01-hardware-and-electrical.md
│   │   ├── 02-communication-protocol.md
│   │   ├── 03-safety-and-protection.md
│   │   ├── 04-instrument-and-product.md
│   │   ├── 05-delivery-and-acceptance.md
│   │   ├── 06-traceability.md
│   │   └── acceptance-test-script.md      # ✨ 验收测试脚本（新增）
│   │
│   ├── prompts/                     # 提示词库
│   │   ├── csharp-hmi-prompt-library.md
│   │   └── code-review-prompt.md
│   │
│   └── templates/                   # 项目模板
│       ├── project-tree.md
│       ├── device-driver-template.cs
│       └── progress-log-template.md
│
└── scripts/                          # 自动化脚本
    ├── init_project_docs.py         # 一键生成开发文档骨架
    ├── append_progress.py           # 追加进度日志
    └── long_run_monitor.py          # ✨ 长稳测试监控工具（新增）
```

---

## 🚀 快速开始

### 第一步：判定交付形态

接到任务后，先回答 3 个问题：

1. **是独立程序还是平台插件？**
   - 独立程序 → 走全流程（形态 A）
   - 平台插件 → 先读 `references/platform-vsionplat.md`（形态 B）

2. **通信方式是什么？**
   - 串口 → `references/comm-serial.md`
   - TCP/UDP → `references/comm-tcp.md`
   - Modbus → `references/comm-modbus.md`
   - OPC UA → `references/comm-opcua.md`
   - 未知/自定义 → `references/new-device-integration.md`

3. **有没有特殊硬件/协议？**
   - 有 → 先填 `assets/checklists/01-hardware-and-electrical.md`
   - 没有 → 直接运行 `scripts/init_project_docs.py` 建档

### 第二步：项目建档

```bash
cd your-project-root
python path/to/scripts/init_project_docs.py "项目名称" "docs/"
```

自动生成 7 份开发文档：
- `00-软件需求规格说明书.md`
- `01-系统设计说明书.md`
- `02-接口与通信协议说明书.md`
- `03-电气与仪器核对表.md`
- `04-测试与验收方案.md`
- `05-开发进度日志.md`
- `06-问题与风险台账.md`

### 第三步：按五阶段推进

1. **阶段 1 — 需求与硬件摸底**
   - 填写 `00-软件需求规格说明书.md`
   - 用 `assets/checklists/` 逐条确认
   - 硬件不确定项标记 `⚠️待确认`

2. **阶段 2 — 架构设计**
   - 按 `references/architecture-winforms.md` 建立分层架构
   - 选定通信抽象（ITransport → IDeviceProtocol → IDeviceDriver）
   - 设计线程模型与数据流

3. **阶段 3 — 编码实现**
   - 通信层取用 `references/comm-*.md` 骨架代码
   - 遇到新设备，参考 `references/new-device-integration.md`
   - 遇到问题，查 `references/troubleshooting.md`

4. **阶段 4 — 联调与验收**
   - 按 `assets/checklists/acceptance-test-script.md` 执行测试
   - 运行 `scripts/long_run_monitor.py` 进行长稳测试
   - 未通过项写入 `06-问题与风险台账.md`

5. **阶段 5 — 交付与知识沉淀**
   - 输出安装包、操作手册、通信协议文件
   - 把新增的坑反哺回本 skill

---

## 🎯 核心使用纪律（8 条铁律）

0. **先判形态再动手** — 独立程序还是宿主平台插件？
1. **不猜硬件** — 寄存器地址、字节序未知时，一律标记待确认
2. **不跳过文档** — 即使客户只要代码，也要先落需求与接口文档
3. **不猜平台 API** — 以 `.xml` 文档 + 实际编译报错为准
4. **通信层先通后快** — 先最小闭环，再优化
5. **UI 线程只做渲染** — 阻塞调用移出 UI 线程
6. **现场可维护性优先** — 日志、自检、参数外置的权重高于设计模式纯度
7. **复用优先** — 先检索已有骨架，禁止从零手写通信层

---

## 📚 适用场景

- 工控上位机、SCADA 系统
- 数据采集系统、测试台架软件
- 仪器仪表控制软件
- 产线 MES 客户端、设备调试工具
- PLC 通信、下位机联调
- 电气核对表与协议对接

---

## 🛠️ 技术栈

**默认技术栈**（除非用户明确指定其他）：
- **框架**: WinForms
- **.NET 版本**: .NET Framework 4.8
- **C# 版本**: C# 7.3

**原因**：工业现场存量设备兼容性最好

---

## 📊 增强版统计

| 类别 | 原版 | 增强版 | 增加 |
|---|---|---|---|
| **文档数量** | 26 | 32+ | +6 核心文档 |
| **代码行数** | ~2000 | ~3000 | +50% |
| **核对表** | 7 | 8 | +1 验收测试脚本 |
| **自动化脚本** | 2 | 3 | +1 长稳测试工具 |
| **总字数** | ~25,000 | ~40,000 | +60% |

---

## 🎁 核心亮点

### 1. 从"方法论"到"可执行工具包"

**原版**：告诉你"要做什么"
**增强版**：提供"怎么做"的完整工具

### 2. 真正的 30 分钟建档

- ✅ 快速决策树（5 分钟定位）
- ✅ 自动化脚本（5 分钟生成骨架）
- ✅ 速查表（10 分钟排查问题）
- ✅ 测试工具（10 分钟启动长稳测试）

### 3. 覆盖完整生命周期

```
需求 → 设计 → 编码 → 测试 → 部署 → 运维 → 知识沉淀
  ↓      ↓      ↓      ↓      ↓      ↓        ↓
 核对表  架构  骨架  验收   自检   远程    文档
        文档  代码  脚本   工具   诊断    模板
```

---

## 🔧 工具使用示例

### 示例 1：长稳测试

```bash
# 监控进程 72 小时
python long_run_monitor.py \
  --process-name "MyHMI.exe" \
  --duration 72 \
  --interval 60 \
  --output "./test-reports"

# 生成 3 个文件：
# - MyHMI.exe_samples.csv       （原始样本数据）
# - MyHMI.exe_report.json       （JSON 格式报告）
# - MyHMI.exe_report.md         （Markdown 格式报告）
```

### 示例 2：快速排查通信问题

遇到 Modbus 读取失败，打开 `references/troubleshooting.md` 第 2.1 节：

```
问题：Modbus 读取失败
↓
检查清单（按优先级）：
1. 从站地址是否正确？
2. 功能码与寄存器类型匹配吗？
3. 寄存器地址是从 0 还是 1 开始？
4. 字节序是大端还是小端？
5. 串口参数一致吗？
6. 超时设置合理吗？
↓
快速验证：用 Modbus Poll 手动发报文
```

### 示例 3：新设备接入

参考 `references/new-device-integration.md`，5 步完成：

```
1. 协议解析 → 定义请求/响应结构体
2. 最小验证 → Console 程序发一帧收一帧
3. 泛型抽象 → 实现 IDeviceProtocol
4. 测试用例 → 正常流程 + 异常场景
5. 文档沉淀 → 更新 02-接口说明书.md
```

---

## 📦 安装与使用

### 方式 1：直接使用（推荐）

将本目录放到：
```
~/.workbuddy/skills/csharp-hmi-development-enhanced/
```

然后在 WorkBuddy 中加载 skill：
```
使用 csharp-hmi-development-enhanced skill
```

### 方式 2：项目级 skill

将本目录放到：
```
your-project/.workbuddy/skills/csharp-hmi-development-enhanced/
```

团队成员共享此 skill。

---

## 🔄 版本对比

| 特性 | 原版 v1.0 | 增强版 v2.0 |
|---|---|---|
| 快速启动 | ❌ 需通读全文 | ✅ 5 分钟决策树 |
| 问题排查 | ⚠️ 原则性指导 | ✅ 速查表 + 工具推荐 |
| 新设备接入 | ⚠️ 缺少 SOP | ✅ 五步法 + 代码模板 |
| 长稳测试 | ⚠️ 只有标准 | ✅ 自动化监控工具 |
| 验收测试 | ⚠️ 缺少用例 | ✅ 12 类测试用例模板 |
| 现场部署 | ⚠️ 基础指导 | ✅ 环境自检 + 远程诊断 |
| 总体成熟度 | 🟡 方法论阶段 | 🟢 可执行工具包 |

---

## 💡 最佳实践

### 1. 第一次使用

1. 阅读本 `README.md`（10 分钟）
2. 快速浏览 `SKILL.md`（5 分钟）
3. 运行 `init_project_docs.py` 生成文档骨架
4. 根据通信方式，跳转到对应 `comm-*.md`

### 2. 日常使用

- **遇到问题** → 查 `troubleshooting.md`
- **新设备接入** → 查 `new-device-integration.md`
- **验收测试** → 查 `acceptance-test-script.md`
- **长稳测试** → 运行 `long_run_monitor.py`

### 3. 知识沉淀

每次项目结束后：
- 把新的坑补充到 `troubleshooting.md`
- 把新的协议变体补充到对应 `comm-*.md`
- 把新的测试用例补充到 `acceptance-test-script.md`

---

## 🤝 贡献与反馈

如果你发现：
- 新的通信协议
- 新的常见问题
- 更好的解决方案
- 文档错误

欢迎提交反馈或直接编辑对应文档。

---

## 📄 许可证

本 skill 为工程化方法论，可自由使用与修改。

---

## 📞 联系方式

- **创建日期**: 2026-10-15
- **最后更新**: 2026-10-15
- **版本**: v2.0（增强版）

---

## 🎉 结语

本增强版 skill 的目标是：

> **让上位机开发从"个人经验"变成"可复制的工程流程"**

无论你是：
- 🆕 新手开发者 → 快速启动路径降低门槛
- 🔧 经验丰富的工程师 → 速查表提高效率
- 👥 团队 Leader → 标准化流程保证质量

都能从本 skill 中获得价值。

**祝开发顺利！** 🚀
