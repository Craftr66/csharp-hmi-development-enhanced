# 工控上位机 UI 设计规范（WinForms）

## 1. 设计原则

工控界面与消费级软件的评判标准完全不同：

| 维度 | 消费级软件 | 工控上位机 |
|---|---|---|
| 首要目标 | 好看、易上手 | **不出错、看得清、响应快** |
| 用户 | 有耐心、可学习 | 赶节拍的现场操作工 |
| 操作环境 | 安静、室内 | 嘈杂、强光/暗光、可能戴手套 |
| 错误代价 | 体验差 | **设备损坏、产品报废、人身伤害** |
| 使用时长 | 碎片化 | 连续 8-12 小时 |

**核心结论**：工控界面优先"防错"与"可读"，美学与动效是次要的。

## 2. 布局规范

### 2.1 布局容器选型

| 需求 | 控件 | 理由 |
|---|---|---|
| 整体页面分区 | `TableLayoutPanel` | 自动按比例分配，缩放稳定 |
| 工具栏/状态栏 | `ToolStrip` + `Dock` | 标准做法，自动适应宽度 |
| 主显示区可调整 | `SplitContainer` | 用户可拖拽调整比例 |
| 数据表格 | `DataGridView`（`Dock=Fill`） | 自动填充 |
| 卡片式区域 | `Panel` + `Padding` | 简单可控 |

**禁止** 使用绝对坐标（`Location` 硬编码）布局主界面——换分辨率必乱。

```csharp
// ✅ 用 TableLayoutPanel 做响应式布局
var layout = new TableLayoutPanel
{
    Dock = DockStyle.Fill,
    ColumnCount = 2,
    RowCount = 3
};
layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 30F));  // 左侧控制区
layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 70F));  // 右侧显示区
layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 60F));       // 标题栏
layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));       // 内容
layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 30F));       // 状态栏
```

### 2.2 分辨率适配

目标分辨率清单必须与客户确认，典型：1366×768（老工控机）、1920×1080（主流）、2560×1440（检测站）。

- [ ] 使用 `Dock` / `Anchor` 而非绝对坐标
- [ ] `AutoScaleMode = Font`（不是 Dpi，WinForms 下 Font 更稳定）
- [ ] 最小窗口尺寸已设置（`MinimumSize`）
- [ ] 布局无重叠、无截断
- [ ] 字体不硬编码（跟随系统或配置）
- [ ] 高 DPI 下用 `PerMonitorV2` 或 `SystemAware`
- [ ] 缩放 125% / 150% 下无错位

### 2.3 触摸屏适配

- [ ] 可点击控件最小尺寸 **≥ 40×40 px**（戴手套需 ≥ 48×48）
- [ ] 可点击控件间距 ≥ 10px（防误触）
- [ ] 关键按钮尺寸 ≥ 80×60 px
- [ ] 不需要悬停（hover）才能看到的信息
- [ ] 下拉框尽量改为大按钮或列表
- [ ] 数值输入提供大键盘（自绘数字键盘）
- [ ] 滚动区域有明确的滚动条
- [ ] 避免 `DataGridView` 单元格直接编辑（触摸下体验差）

## 3. 视觉规范

### 3.1 配色

```csharp
// 工控推荐配色（浅色主题）
public static class HmiColors
{
    // 背景
    public static readonly Color WindowBg      = Color.FromArgb(240, 242, 245);
    public static readonly Color PanelBg       = Color.White;
    public static readonly Color HeaderBg      = Color.FromArgb(45, 55, 72);

    // 文字
    public static readonly Color TextPrimary   = Color.FromArgb(33, 37, 41);
    public static readonly Color TextSecondary = Color.FromArgb(108, 117, 125);
    public static readonly Color TextInverse   = Color.White;

    // 状态（工控语义）
    public static readonly Color Running    = Color.FromArgb(40, 167, 69);    // 运行 绿
    public static readonly Color Stopped    = Color.FromArgb(108, 117, 125);  // 停止 灰
    public static readonly Color Warning    = Color.FromArgb(255, 152, 0);    // 警告 橙
    public static readonly Color Alarm      = Color.FromArgb(220, 53, 69);    // 报警 红
    public static readonly Color Fault      = Color.FromArgb(153, 0, 0);      // 故障 深红
    public static readonly Color Disabled   = Color.FromArgb(200, 200, 200);  // 禁用
    public static readonly Color Highlight  = Color.FromArgb(0, 123, 255);    // 选中 蓝

    // 边框
    public static readonly Color Border     = Color.FromArgb(222, 226, 230);
    public static readonly Color GridLine   = Color.FromArgb(233, 236, 239);
}
```

**配色要求**：

- 对比度 ≥ 4.5:1（WCAG AA）
- **不依赖颜色单独传达信息**（色盲友好）：报警同时用图标 + 文字
- 状态色一致：全文一个"运行"只用一个绿
- 深色区域用浅色字，浅色区域用深色字（**不要用浅灰字**）
- 避免纯黑（`Color.Black`）与纯白（`Color.White`），用 `33,37,41` 与 `248,249,250`
- 避免高饱和背景大面积使用（长时间注视疲劳）

### 3.2 字体

```csharp
// 推荐：等线 / 微软雅黑 / Segoe UI
// 数值显示必须用等宽字体，防止跳动
public static class HmiFonts
{
    public const string UiFont       = "Microsoft YaHei UI";
    public const string NumberFont   = "Consolas";           // 等宽，数值对齐

    public static Font Title    => new Font(UiFont, 16F, FontStyle.Bold);
    public static Font Subtitle => new Font(UiFont, 12F, FontStyle.Bold);
    public static Font Body     => new Font(UiFont, 10F);
    public static Font Caption  => new Font(UiFont, 9F);

    /// <summary>实时数值：等宽 + 大字号，远距离可读</summary>
    public static Font BigValue => new Font(NumberFont, 36F, FontStyle.Bold);
    public static Font Unit     => new Font(UiFont, 11F);
}
```

**字号要求**：

- 实时关键数值：**≥ 24pt**（3 米外可读）
- 一般数值：≥ 12pt
- 标签文字：≥ 9pt
- 报警文字：≥ 14pt
- **禁止** 用 8pt 以下字体

### 3.3 间距

```
外边距：16px
卡片内边距：12-16px
控件间距：8-12px
分组间距：20-24px
```

## 4. 实时数据展示

### 4.1 数值显示（防跳动）

```csharp
/// <summary>等宽数字 + 固定小数位，避免数值变化时宽度跳动</summary>
public sealed class ValueLabel : Control
{
    private double _value;
    private string _format = "F2";
    private string _unit = "";

    public double Value
    {
        get => _value;
        set
        {
            if (Math.Abs(_value - value) < double.Epsilon) return;
            _value = value;
            Invalidate();               // 只重绘，不重建
        }
    }

    public string Format { get => _format; set { _format = value; Invalidate(); } }
    public string Unit { get => _unit; set { _unit = value; Invalidate(); } }

    public ValueLabel()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint |
                 ControlStyles.UserPaint |
                 ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw, true);
        Font = HmiFonts.BigValue;
        ForeColor = HmiColors.TextPrimary;
        BackColor = Color.Transparent;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        e.Graphics.Clear(Parent?.BackColor ?? BackColor);

        var text = _value.ToString(_format);
        var size = e.Graphics.MeasureString(text, Font);
        var y = (Height - size.Height) / 2;
        e.Graphics.DrawString(text, Font, new SolidBrush(ForeColor), 0, y);

        if (!string.IsNullOrEmpty(_unit))
        {
            using (var unitFont = HmiFonts.Unit)
            using (var brush = new SolidBrush(HmiColors.TextSecondary))
                e.Graphics.DrawString(_unit, unitFont, brush, size.Width + 4, y + size.Height * 0.5f);
        }
    }
}
```

### 4.2 状态指示

```csharp
public sealed class StatusIndicator : Control
{
    private DeviceState _state = DeviceState.Disconnected;

    public DeviceState State
    {
        get => _state;
        set
        {
            if (_state == value) return;
            _state = value;
            Invalidate();
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var color = _state switch
        {
            DeviceState.Connected    => HmiColors.Running,
            DeviceState.Connecting   => HmiColors.Warning,
            DeviceState.Reconnecting => HmiColors.Warning,
            DeviceState.Faulted      => HmiColors.Alarm,
            _                        => HmiColors.Stopped
        };

        int r = Math.Min(Width, Height) - 4;
        using (var brush = new SolidBrush(color))
            e.Graphics.FillEllipse(brush, 2, 2, r, r);

        using (var pen = new Pen(Color.FromArgb(60, 0, 0, 0), 1))
            e.Graphics.DrawEllipse(pen, 2, 2, r, r);
    }
}
```

## 5. 实时曲线（性能关键）

**这是上位机最容易做出性能问题的地方。**

### 5.1 方案对比

| 方案 | 性能 | 灵活性 | 推荐场景 |
|---|---|---|---|
| `Chart`（微软自带） | 差（点数 >1万 卡） | 一般 | 点数少的简单图表 |
| `DataGridView` 拼图 | 极差 | 无 | 禁止 |
| 自绘 `Control`（GDI+） | 好（可控） | 高 | **推荐** |
| `PictureBox` + Bitmap | 好 | 中 | 固定静态图 |
| 第三方（OxyPlot / ScottPlot） | 好 | 高 | 可考虑，注意授权 |

### 5.2 自绘曲线实现要点

```csharp
public sealed class RealtimeChart : Control
{
    private readonly List<SeriesBuffer> _series = new List<SeriesBuffer>();
    private readonly object _sync = new object();
    private int _windowPoints = 5000;
    private double _yMin, _yMax;

    public RealtimeChart()
    {
        // ⚠️ 三个关键样式，缺一就会闪烁
        SetStyle(ControlStyles.AllPaintingInWmPaint |
                 ControlStyles.UserPaint |
                 ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.ResizeRedraw, true);

        // ⚠️ 禁用背景擦除以进一步减少闪烁
        UpdateStyles();
    }

    /// <summary>批量追加，避免逐点触发重绘</summary>
    public void AppendBatch(string seriesName, double[] values)
    {
        lock (_sync)
        {
            var s = _series.FirstOrDefault(x => x.Name == seriesName);
            if (s == null) { s = new SeriesBuffer(seriesName, _windowPoints); _series.Add(s); }
            s.Append(values);
        }
        // 不在这里 Invalidate，由外部定时器统一刷新
    }

    public void Refresh2() => Invalidate();

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.SmoothingMode = SmoothingMode.None;   // 曲线用 None 更快
        e.Graphics.Clear(HmiColors.PanelBg);

        lock (_sync)
        {
            if (_series.Count == 0) return;

            // 1) 计算 Y 轴范围（避免每帧遍历全部点）
            ComputeRange();

            // 2) 画网格（用缓存的 Pen，不要每次 new）
            DrawGrid(e.Graphics);

            // 3) 画曲线：**关键 —— 按像素列降采样**
            foreach (var s in _series)
                DrawSeriesDownsampled(e.Graphics, s);
        }
    }

    /// <summary>按像素列取该列的最大最小值，点数 > 像素数时效果等同但不失真</summary>
    private void DrawSeriesDownsampled(Graphics g, SeriesBuffer s)
    {
        int w = Width, h = Height;
        if (w <= 1 || s.Count == 0) return;

        double span = _yMax - _yMin;
        if (span <= 0) span = 1;

        using (var pen = s.GetPen())
        {
            var pts = new PointF[Math.Min(w, s.Count)];
            int pi = 0;
            int step = Math.Max(1, s.Count / w);

            for (int x = 0; x < w && pi < pts.Length; x++)
            {
                int startIdx = s.StartIndex + x * step;
                if (startIdx >= s.StartIndex + s.Count) break;

                double min = double.MaxValue, max = double.MinValue;
                for (int k = 0; k < step && startIdx + k < s.StartIndex + s.Count; k++)
                {
                    double v = s[startIdx + k];
                    if (v < min) min = v;
                    if (v > max) max = v;
                }

                float yMax = h - (float)((max - _yMin) / span * h);
                float yMin = h - (float)((min - _yMin) / span * h);
                pts[pi++] = new PointF(x, (yMax + yMin) / 2);
            }

            if (pi > 1) g.DrawLines(pen, pts.Take(pi).ToArray());
        }
    }

    private void ComputeRange()
    {
        double min = double.MaxValue, max = double.MinValue;
        foreach (var s in _series)
        {
            s.GetRange(out double smin, out double smax);
            if (smin < min) min = smin;
            if (smax > max) max = smax;
        }
        if (min > max) { min = 0; max = 1; }
        double pad = (max - min) * 0.1;
        if (pad <= 0) pad = 1;
        _yMin = min - pad;
        _yMax = max + pad;
    }

    // DrawGrid / SeriesBuffer 实现略
}
```

### 5.3 曲线性能清单

- [ ] 双缓冲已开启（`OptimizedDoubleBuffer`）
- [ ] 按像素列降采样（点数 > 宽度时）
- [ ] 批量刷新（由 Timer 驱动，而非数据到达即刷新）
- [ ] Pen / Brush 缓存复用（不在 OnPaint 里 new）
- [ ] 环形缓冲存点（不用 `List.RemoveAt(0)`）
- [ ] 刷新率 ≤ 30Hz（人眼无需更高）
- [ ] 可见通道数限制（>8 通道考虑分组显示）
- [ ] Y 轴范围计算不遍历全量点
- [ ] 缩放/平移不引起全量重算

## 6. 报警面板

```csharp
// 需求：报警滚动列表，高频报警不卡界面
// 方案：虚拟化列表 或 自绘固定行数

public sealed class AlarmPanel : Control
{
    private const int MaxVisibleRows = 20;
    private readonly Queue<AlarmItem> _recent = new Queue<AlarmItem>(1000);
    private readonly object _sync = new object();

    public void AddAlarm(AlarmItem item)
    {
        lock (_sync)
        {
            _recent.Enqueue(item);
            while (_recent.Count > 1000) _recent.Dequeue();   // 限制内存
        }
        // 由外部 Timer 统一 Invalidate，避免高频报警刷爆 UI
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        // 只画最近 MaxVisibleRows 条 —— 无论历史多少，绘制量恒定
        // 未确认报警用红色背景 + 闪烁（用 Timer 切换透明度，不重绘全部）
    }
}
```

**报警设计原则**：

- 分级：提示（蓝） / 警告（橙） / 严重（红） / 致命（深红 + 闪烁）
- 必须支持人工确认（Ack），未确认持续显示
- 必须记录历史（时间、设备、内容、确认人）
- 高频报警必须有抑制/合并机制（避免刷屏）
- 声音可关闭（夜班场景），但关闭状态需可见
- 关键报警不能只靠颜色（色盲），要有图标 + 文字

## 7. 无闪烁刷新清单

| 措施 | 说明 |
|---|---|
| `SetStyle(OptimizedDoubleBuffer)` | 双缓冲，必开 |
| `SetStyle(AllPaintingInWmPaint)` | 不在 WM_ERASEBKGND 擦背景 |
| `SetStyle(UserPaint)` | 自绘全部内容 |
| `SetStyle(ResizeRedraw)` | 改变大小时重绘 |
| 避免 `Control.Refresh()` | 强制同步重绘，用 `Invalidate()` 异步 |
| 避免在 `OnPaint` 里 new 对象 | 缓存 Pen/Brush/Font |
| 避免频繁 `Controls.Add/Remove` | 布局重算极慢，用 `Visible` 切换 |
| `SuspendLayout/ResumeLayout` | 批量改布局时包裹 |
| 大量数据用虚拟化 | `DataGridView.VirtualMode = true` |
| 表格批量更新用 `BindingList` + `RaiseListChangedEvents = false` | 避免逐行事件 |

```csharp
// 表格批量更新的正确姿势
var list = (BindingList<MyRow>)grid.DataSource;
list.RaiseListChangedEvents = false;   // 暂停事件
try
{
    foreach (var r in batch) list.Add(r);
}
finally
{
    list.RaiseListChangedEvents = true;
    list.ResetBindings();              // 一次性通知
}
```

## 8. 交互设计

### 8.1 防错设计

- [ ] 高危操作按钮位置远离常用操作
- [ ] 高危操作需二次确认（显示"旧值 → 新值"）
- [ ] 极危操作需输入确认文本（如输入设备名）
- [ ] 按钮点击后立即禁用（防重复提交）
- [ ] 长时间操作有进度与取消
- [ ] 输入框有范围校验与即时提示
- [ ] 必填项有明确标识
- [ ] 保存失败有明确错误提示（不要弹"操作失败"就完事）

```csharp
private async void btnWriteParam_Click(object sender, EventArgs e)
{
    var btn = (Button)sender;
    var oldValue = _vm.CurrentValue;
    var newValue = (double)numValue.Value;

    // 1) 范围校验
    if (newValue < _vm.MinValue || newValue > _vm.MaxValue)
    {
        MessageBox.Show(this, $"输入 {newValue} 超出允许范围 [{_vm.MinValue}, {_vm.MaxValue}]",
            "输入非法", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        return;
    }

    // 2) 二次确认（显示旧值→新值）
    if (MessageBox.Show(this,
            $"确认修改变量 [{_vm.TagName}]？\n\n当前值：{oldValue:F2}\n新值：{newValue:F2}\n\n" +
            "该操作将立即下发到设备，请确认。",
            "高危操作确认", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2) != DialogResult.Yes)
        return;

    // 3) 立即禁用防重复提交
    btn.Enabled = false;
    try
    {
        await _vm.WriteAsync(newValue);
        // 4) 回读校验
        var readback = await _vm.ReadAsync();
        if (Math.Abs(readback - newValue) > 0.01)
            MessageBox.Show(this, $"写入未生效！期望 {newValue:F2}，回读 {readback:F2}",
                "写入异常", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
    catch (Exception ex)
    {
        _logger.Error(ex, "写入参数失败");
        MessageBox.Show(this, ex.Message, "写入失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
    finally
    {
        btn.Enabled = true;
    }
}
```

### 8.2 反馈设计

| 操作 | 反馈方式 | 时长 |
|---|---|---|
| 按钮点击 | 状态变化 + 禁用 | 立即 |
| 短时操作（<1s） | 状态栏提示 | 2 秒 |
| 中时操作（1-5s） | 进度条（不确定型） | 持续 |
| 长时操作（>5s） | 进度条 + 百分比 + 取消按钮 | 持续 |
| 成功 | 状态栏绿色提示 / Toast | 3 秒 |
| 失败 | 弹窗（含原因与建议） | 需确认 |
| 危险确认 | 弹窗（默认焦点在"否"） | 需确认 |

**禁止**：操作后无任何反馈；用 `MessageBox` 提示"操作成功"（打断操作流）。

### 8.3 键盘支持

现场操作员常全键盘操作：

- [ ] Tab 顺序合理（从左到右、从上到下）
- [ ] 回车触发默认按钮（`AcceptButton`）
- [ ] Esc 关闭对话框（`CancelButton`）
- [ ] 快捷键：F1 帮助、F5 刷新、Ctrl+S 保存、空格暂停
- [ ] 功能键映射到常用操作（现场会贴标签提示）
- [ ] 输入框全选（`SelectAll` on Enter）

## 9. 多语言与本地化

```csharp
// 所有界面文本从资源读取，禁止硬编码
this.Text = Strings.MainWindowTitle;
btnStart.Text = Strings.StartAcquisition;

// 单位与小数位从配置读取
_valueLabel.Format = _cfg.Get<string>("Display.PressureFormat", "F3");
_valueLabel.Unit = _cfg.Get<string>("Display.PressureUnit", "MPa");
```

- [ ] 界面文本外置到 `.resx`
- [ ] 数值格式（小数位）可配置
- [ ] 单位可配置（公制/英制）
- [ ] 时间格式可配置（24h / 12h）
- [ ] 中文字体在目标系统可用（避免宋体乱码）
- [ ] 长英文文本的控件宽度足够（英文比中文长）

## 10. 启动与关闭体验

**启动**：
- [ ] 显示 Splash 或启动进度（初始化数据库、加载配置、连接设备）
- [ ] 启动失败给出明确原因（而不是闪退）
- [ ] 设备连接过程可见（哪些连上了、哪些没连上）
- [ ] 启动时间 ≤ 10 秒（超过需显示进度）

**关闭**：
- [ ] 有关键任务运行时弹确认
- [ ] 显示"正在保存数据..."进度
- [ ] 超时保护（不能无限等待）
- [ ] 异常时也要能强制退出

## 11. UI 评审清单

- [ ] 在目标分辨率下无重叠、无截断
- [ ] 高 DPI（125%/150%）下布局正确
- [ ] 触摸操作按钮尺寸足够
- [ ] 关键数值远距离可读（≥24pt）
- [ ] 报警有明显视觉 + 听觉提示
- [ ] 颜色对比度 ≥4.5:1
- [ ] 不只靠颜色传达信息
- [ ] 界面刷新无闪烁
- [ ] 高频数据更新界面不卡
- [ ] 所有操作用户可感知
- [ ] 高危操作有二次确认
- [ ] 长时间操作有进度与取消
- [ ] 键盘可完成主要操作
- [ ] 界面文本可配置
- [ ] 无硬编码字体与颜色
- [ ] 启动有进度、关闭有确认
