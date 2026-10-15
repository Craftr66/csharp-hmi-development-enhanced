# 数据存储与性能调优规范

## 第一部分：数据存储

### 1. 数据库选型

| 场景 | 推荐 | 理由 |
|---|---|---|
| 单机、中小数据量（<1亿条） | **SQLite** | 零部署、单文件、稳定 |
| 多客户端、大数据量 | SQL Server Express / 标准版 | 并发好、工具成熟 |
| 跨平台/客户已有 | MySQL / PostgreSQL | |
| 高频写入、时序数据（>10万点/秒） | 时序库（InfluxDB / TDengine） | 压缩率高、查询快 |
| 仅需日志式追加 | 二进制文件 + 索引 | 最快，但查询弱 |

**默认建议**：单机上位的采集与测试数据用 **SQLite**。它足够快（配合正确的批量提交可到 10 万条/秒），且零运维。

### 2. SQLite 工程化配置

```csharp
public static class SqliteFactory
{
    /// <summary>创建针对高频写入优化过的连接</summary>
    public static SQLiteConnection Create(string dbPath, bool readOnly = false)
    {
        var builder = new SQLiteConnectionStringBuilder
        {
            DataSource = dbPath,
            Version = 3,
            ReadOnly = readOnly,
            // ⚠️ 关键性能参数
            JournalMode = SQLiteJournalMode.WAL,   // WAL：读写并发，写入不阻塞读
            SyncMode = SQLiteSyncMode.Normal,      // WAL 下 Normal 已足够安全
            CacheSize = -64000,                    // 64MB 页缓存（负数为字节）
            PageSize = 4096,
            Pooling = true,                        // 连接池
            BusyTimeout = 5000,                    // 忙等待 5 秒，避免 database is locked
            ForeignKeys = false                    // 若不需要外键约束，关掉可提速
        };

        var conn = new SQLiteConnection(builder.ToString());
        conn.Open();

        // 常用 PRAGMA（每次连接都需要设置）
        using (var cmd = conn.CreateCommand())
        {
            cmd.CommandText = @"
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA temp_store=MEMORY;
                PRAGMA mmap_size=268435456;   -- 256MB 内存映射
                PRAGMA foreign_keys=OFF;";
            cmd.ExecuteNonQuery();
        }
        return conn;
    }
}
```

> ⚠️ WAL 模式会生成 `-wal` 和 `-shm` 文件，备份时需一并复制，或用 `VACUUM INTO` 做一致性备份。

### 3. 表结构设计

```sql
-- 采集数据主表
CREATE TABLE IF NOT EXISTS Sample (
    Id          INTEGER PRIMARY KEY AUTOINCREMENT,
    DeviceId    TEXT    NOT NULL,
    TagName     TEXT    NOT NULL,
    Value       REAL    NOT NULL,
    Quality     INTEGER NOT NULL DEFAULT 0,   -- 0=Good, 非0=坏值
    Timestamp   INTEGER NOT NULL              -- Unix 毫秒
);

-- 索引策略：按时间查询是主场景
CREATE INDEX IF NOT EXISTS idx_sample_time ON Sample(Timestamp);
CREATE INDEX IF NOT EXISTS idx_sample_device_time ON Sample(DeviceId, Timestamp);

-- 报警记录
CREATE TABLE IF NOT EXISTS Alarm (
    Id          INTEGER PRIMARY KEY AUTOINCREMENT,
    DeviceId    TEXT,
    TagName     TEXT,
    Level       INTEGER NOT NULL,             -- 1提示 2警告 3严重 4致命
    Message     TEXT NOT NULL,
    Value       REAL,
    RaisedAt    INTEGER NOT NULL,
    AckedAt     INTEGER,                      -- NULL 表示未确认
    AckedBy     TEXT
);
CREATE INDEX IF NOT EXISTS idx_alarm_raised ON Alarm(RaisedAt);
CREATE INDEX IF NOT EXISTS idx_alarm_acked ON Alarm(AckedAt) WHERE AckedAt IS NULL;

-- 操作日志（只追加，不可修改）
CREATE TABLE IF NOT EXISTS OperationLog (
    Id          INTEGER PRIMARY KEY AUTOINCREMENT,
    Timestamp   INTEGER NOT NULL,
    UserName    TEXT,
    MachineName TEXT,
    SoftwareVersion TEXT,
    Action      TEXT NOT NULL,
    Target      TEXT,
    OldValue    TEXT,
    NewValue    TEXT,
    Result      INTEGER NOT NULL,             -- 0失败 1成功
    Message     TEXT
);

-- 数据库结构版本（用于自动迁移）
CREATE TABLE IF NOT EXISTS SchemaVersion (
    Version     INTEGER PRIMARY KEY,
    AppliedAt   INTEGER NOT NULL,
    Description TEXT
);

-- 追溯用：设备与软件版本台账
CREATE TABLE IF NOT EXISTS EquipmentLedger (
    Id          INTEGER PRIMARY KEY AUTOINCREMENT,
    Workstation TEXT,
    SoftwareVersion TEXT,
    InstrumentModel TEXT,
    InstrumentSerial TEXT,
    CommunicationAddress TEXT,
    RecordedAt  INTEGER NOT NULL
);
```

### 4. 批量写入管道（关键性能实现）

```csharp
public sealed class BulkWritePipeline : IDisposable
{
    private readonly BlockingCollection<SampleBatch> _queue;
    private readonly string _connectionString;
    private readonly ILogService _logger;
    private readonly Task _consumer;
    private readonly CancellationTokenSource _cts;

    private long _enqueued, _written, _dropped;

    public BulkWritePipeline(string connectionString, ILogService logger,
                             int queueCapacity = 500, int batchSize = 5000,
                             int flushIntervalMs = 1000)
    {
        _connectionString = connectionString;
        _logger = logger;
        // ⚠️ 必须有界！无界队列在磁盘慢时会吃掉全部内存
        _queue = new BlockingCollection<SampleBatch>(queueCapacity);
        _cts = new CancellationTokenSource();
        _consumer = Task.Run(() => ConsumeAsync(batchSize, flushIntervalMs, _cts.Token));
    }

    public bool TryEnqueue(SampleBatch batch)
    {
        // ⚠️ 队列满时丢弃 + 计数 + 限频告警，绝不阻塞采集线程
        if (!_queue.TryAdd(batch))
        {
            long dropped = Interlocked.Increment(ref _dropped);
            if (dropped % 100 == 1)
                _logger.Warn($"落库队列已满，累计丢弃 {dropped} 批（磁盘或数据库可能过慢）");
            return false;
        }
        Interlocked.Increment(ref _enqueued);
        return true;
    }

    private async Task ConsumeAsync(int batchSize, int flushIntervalMs, CancellationToken ct)
    {
        using (var conn = SqliteFactory.Create(_connectionString))
        {
            var buffer = new List<Sample>(batchSize * 2);
            var lastFlush = DateTime.UtcNow;

            try
            {
                foreach (var batch in _queue.GetConsumingEnumerable(ct))
                {
                    buffer.AddRange(batch.Items);

                    bool shouldFlush =
                        buffer.Count >= batchSize ||
                        (DateTime.UtcNow - lastFlush).TotalMilliseconds >= flushIntervalMs;

                    if (shouldFlush && buffer.Count > 0)
                    {
                        await FlushAsync(conn, buffer, ct).ConfigureAwait(false);
                        Interlocked.Add(ref _written, buffer.Count);
                        buffer.Clear();
                        lastFlush = DateTime.UtcNow;
                    }
                }
            }
            catch (OperationCanceledException) { }

            // 收尾：把剩余数据写完
            if (buffer.Count > 0)
            {
                try { await FlushAsync(conn, buffer, ct).ConfigureAwait(false); }
                catch (Exception ex) { _logger.Error(ex, "退出时写剩余数据失败"); }
            }
        }
    }

    private async Task FlushAsync(SQLiteConnection conn, List<Sample> items, CancellationToken ct)
    {
        // ⚠️ 一个事务包住整批 —— 逐条提交会慢 100 倍以上
        using (var tx = conn.BeginTransaction())
        using (var cmd = conn.CreateCommand())
        {
            cmd.Transaction = tx;
            cmd.CommandText = @"INSERT INTO Sample (DeviceId, TagName, Value, Quality, Timestamp)
                                VALUES (@d, @t, @v, @q, @ts);";

            var pd = cmd.Parameters.Add("@d", DbType.String);
            var pt = cmd.Parameters.Add("@t", DbType.String);
            var pv = cmd.Parameters.Add("@v", DbType.Double);
            var pq = cmd.Parameters.Add("@q", DbType.Int32);
            var pts = cmd.Parameters.Add("@ts", DbType.Int64);
            cmd.Prepare();                       // 预编译，批内复用

            foreach (var s in items)
            {
                pd.Value = s.DeviceId;
                pt.Value = s.TagName;
                pv.Value = s.Value;
                pq.Value = s.Quality;
                pts.Value = s.TimestampMs;
                cmd.ExecuteNonQuery();
            }

            tx.Commit();
        }
        await Task.CompletedTask;
    }

    public StorageStatistics GetStatistics() => new StorageStatistics
    {
        Enqueued = Interlocked.Read(ref _enqueued),
        Written = Interlocked.Read(ref _written),
        Dropped = Interlocked.Read(ref _dropped),
        QueueDepth = _queue.Count
    };

    public void Dispose()
    {
        _queue.CompleteAdding();
        try { _consumer.Wait(10000); }   // 给足收尾时间
        catch (Exception ex) { _logger.Warn($"等待落库任务结束超时：{ex.Message}"); }
        _cts.Cancel();
        _queue.Dispose();
        _cts.Dispose();
    }
}
```

### 5. 数据量估算与控制

**估算公式**：

```
单条记录大小 ≈ 8(Id) + 32(DeviceId) + 32(TagName) + 8(Value) + 4(Quality) + 8(Timestamp)
             ≈ 92 字节（含索引约 150 字节）

日增量 = 点数/秒 × 86400 × 150 字节

示例：
  100 点/秒  → 8.64M 条/天 → 约 1.3 GB/天
  1000 点/秒 → 86.4M 条/天 → 约 13 GB/天   ⚠️ 必须压缩或降采样
```

**控制策略**（按优先级）：

| 策略 | 效果 | 代价 |
|---|---|---|
| 变化死区过滤（只有变化超阈值才存） | 降低 80-95% | 丢失微小变化历史 |
| 降采样存储（1s 存 1 个平均值） | 降低 90%+ | 丢失瞬时细节 |
| 分层存储（近期全量 + 远期聚合） | 平衡 | 实现复杂 |
| 滚动删除（保留 N 天） | 容量恒定 | 历史受限 |
| 数据分区（按月分表/分文件） | 删除快、查询快 | 实现复杂 |

**推荐组合**：**死区过滤 + 分层存储 + 滚动删除**。

```csharp
public sealed class DeadbandFilter
{
    private readonly double _absolute;
    private readonly double _relative;
    private double _lastValue;
    private bool _initialized;

    public DeadbandFilter(double absoluteDeadband, double relativeDeadbandPercent)
    {
        _absolute = absoluteDeadband;
        _relative = relativeDeadbandPercent;
    }

    public bool ShouldRecord(double value)
    {
        if (!_initialized) { _lastValue = value; _initialized = true; return true; }

        double delta = Math.Abs(value - _lastValue);
        double threshold = Math.Max(_absolute, Math.Abs(_lastValue) * _relative / 100.0);

        if (delta >= threshold) { _lastValue = value; return true; }
        return false;
    }
}
```

### 6. 数据滚动清理

```csharp
public sealed class DataRetentionService
{
    private readonly string _connectionString;
    private readonly ILogService _logger;
    private readonly int _retentionDays;

    public async Task CleanupAsync(DateTime utcNow)
    {
        long cutoff = new DateTimeOffset(utcNow.AddDays(-_retentionDays)).ToUnixTimeMilliseconds();

        using (var conn = SqliteFactory.Create(_connectionString))
        {
            // ⚠️ 大表直接 DELETE 会锁库很久，分批删除
            int totalDeleted = 0;
            while (true)
            {
                using (var cmd = conn.CreateCommand())
                {
                    cmd.CommandText = @"
                        DELETE FROM Sample
                        WHERE Id IN (SELECT Id FROM Sample WHERE Timestamp < @c LIMIT 10000);";
                    cmd.Parameters.AddWithValue("@c", cutoff);
                    int n = cmd.ExecuteNonQuery();
                    totalDeleted += n;
                    if (n < 10000) break;
                }
                await Task.Delay(200).ConfigureAwait(false);   // 让出锁，避免阻塞采集
            }

            // 定期 VACUUM 回收空间（很慢，只在低峰期做，且频率不宜高）
            if (totalDeleted > 100000)
            {
                using (var cmd = conn.CreateCommand())
                {
                    cmd.CommandText = "PRAGMA incremental_vacuum;";
                    cmd.ExecuteNonQuery();
                }
            }

            _logger.Info($"数据清理完成，删除 {totalDeleted} 条，保留 {_retentionDays} 天");
        }
    }
}
```

### 7. 备份

```csharp
public static class SqliteBackup
{
    /// <summary>一致性备份（WAL 模式下不能用文件复制）</summary>
    public static void Backup(string sourcePath, string backupPath)
    {
        using (var src = new SQLiteConnection($"Data Source={sourcePath}"))
        using (var dst = new SQLiteConnection($"Data Source={backupPath}"))
        {
            src.Open();
            dst.Open();
            src.BackupDatabase(dst);   // SQLite 在线备份 API，一致且不阻塞
        }
    }
}
```

---

## 第二部分：性能调优

### 8. 性能问题定位流程

```
现象
 ├─ 界面卡顿 ────→ UI 线程阻塞？ → 检查 .Result/.Wait/Thread.Sleep、同步 IO、大循环
 │                绘制过重？     → 检查点数、双缓冲、Pen 复用、刷新率
 │                布局频繁重算？ → 检查 Controls.Add/Remove、Visible 切换
 │
 ├─ CPU 高 ─────→ 忙等？         → 检查 while(true) 无 Delay、轮询无间隔
 │                序列化/解析？  → 检查 JSON/XML 高频解析
 │                字符串处理？   → 检查日志拼接、ToHex
 │                锁竞争？       → 检查 lock 范围
 │
 ├─ 内存增长 ────→ 事件泄漏？     → 检查未取消订阅
 │                缓冲无界？     → 检查队列/List 是否有上限
 │                大对象堆积？   → 检查 LOH（大数组、大字符串）
 │                句柄/位图未释放？→ 检查 GDI 对象
 │
 ├─ 通信延迟 ────→ 轮询周期过长？ → 检查周期 vs 实际耗时
 │                请求未合并？   → 检查是否逐点读取
 │                Nagle 未关？   → 检查 NoDelay
 │                总线冲突？     → 检查 RS485 是否串行化
 │                重试风暴？     → 检查退避策略
 │
 └─ 数据丢失 ────→ 队列溢出？     → 检查有界队列丢弃计数
                    环形缓冲覆盖？→ 检查容量与消费速度
                    异常中断采集？→ 检查异常处理
```

### 9. 关键优化手段

#### 9.1 GC 压力（上位机最常见）

```csharp
// ❌ 高频路径 new 对象
for (int i = 0; i < 1000; i++)
{
    var bytes = BitConverter.ToString(data, i, 1);   // 每次 new string
    _logger.Trace("RX " + bytes);                     // 每次拼 string
}

// ✅ 复用缓冲 + 延迟格式化
private readonly char[] _hexBuf = new char[3];
private readonly StringBuilder _sb = new StringBuilder(8192);

// ✅ 高频路径不做日志字符串拼接（用参数化，级别不足时不格式化）
_logger.Trace("RX {0} len={1}", Name, len);

// ✅ 大数组用 ArrayPool（避免 LOH 分配）
var buf = ArrayPool<byte>.Shared.Rent(65536);
try { /* 使用 */ }
finally { ArrayPool<byte>.Shared.Return(buf); }

// ✅ 避免装箱：泛型约束 struct
public T ReadValue<T>(string tag) where T : struct { }
```

> **LOH 陷阱**：≥85000 字节的对象进入大对象堆，GC 不压缩，会导致碎片化与内存持续增长。典型触发：`byte[100000]`、超大 `string`。对策：分片处理或 `ArrayPool`。

#### 9.2 通信优化

| 优化 | 效果 | 实现 |
|---|---|---|
| 批量读替代逐点读 | 10-50× | 地址归并规划器 |
| 关闭 Nagle | 延迟降 40ms | `NoDelay = true` |
| 复用连接（长连接） | 避免握手开销 | 不用短连接 |
| 订阅替代轮询（OPC UA） | 延迟与流量大幅降低 | Subscription |
| 死区过滤 | 流量降 80%+ | DataChangeFilter |
| 请求间隔优化 | 避免设备过载 | 配置化 |
| 并行多设备 | 总耗时降 N 倍 | 独立 Task（总线不共享时） |

#### 9.3 数据库优化

```sql
-- 查询优化：只取需要的列
SELECT Timestamp, Value FROM Sample WHERE DeviceId=@d AND Timestamp BETWEEN @s AND @e;

-- 分页（避免大偏移量，用 Id 游标）
SELECT * FROM Sample WHERE Id > @lastId ORDER BY Id LIMIT 1000;

-- 聚合查询用索引覆盖
SELECT strftime('%Y-%m-%d %H', Timestamp/1000, 'unixepoch') AS Hour,
       AVG(Value), MIN(Value), MAX(Value)
FROM Sample
WHERE DeviceId=@d AND Timestamp BETWEEN @s AND @e
GROUP BY Hour;

-- 分析查询计划
EXPLAIN QUERY PLAN SELECT ...;
```

#### 9.4 内存与句柄监控

```csharp
public sealed class ResourceMonitor
{
    private Process _proc = Process.GetCurrentProcess();
    private int _lastHandles;
    private long _lastWorkingSet;

    public ResourceSnapshot Sample()
    {
        _proc.Refresh();
        var snap = new ResourceSnapshot
        {
            WorkingSetMB = _proc.WorkingSet64 / 1024 / 1024,
            PrivateMemoryMB = _proc.PrivateMemorySize64 / 1024 / 1024,
            HandleCount = _proc.HandleCount,
            ThreadCount = _proc.Threads.Count,
            GcHeapMB = GC.GetTotalMemory(false) / 1024 / 1024,
            Gen0 = GC.CollectionCount(0),
            Gen1 = GC.CollectionCount(1),
            Gen2 = GC.CollectionCount(2),
            Timestamp = DateTime.UtcNow
        };

        // 增长告警
        if (_lastHandles > 0 && snap.HandleCount - _lastHandles > 500)
            _logger.Warn($"句柄数增长异常：{_lastHandles} → {snap.HandleCount}，疑似泄漏");

        _lastHandles = snap.HandleCount;
        _lastWorkingSet = snap.WorkingSetMB;
        return snap;
    }
}
```

**长稳测试观察指标**：

| 指标 | 健康特征 | 危险信号 |
|---|---|---|
| 工作集内存 | 波动后趋于稳定 | 单调增长不回落 |
| 句柄数 | 稳定 | 持续增长 |
| GDI 对象 | 稳定 | 持续增长 |
| 线程数 | 稳定 | 持续增长 |
| Gen2 GC 次数 | 低频 | 高频（>1次/秒） |
| 通信错误率 | <0.1% | 持续升高 |
| 队列深度 | 低位波动 | 持续满 |

### 10. 性能预算表（设计阶段填写）

| 项 | 预算 | 实测 | 余量 |
|---|---|---|---|
| UI 刷新耗时 | ≤ 16ms（60fps） | | |
| 单次通信往返 | ≤ ___ ms | | |
| 一轮完整轮询 | ≤ ___ ms | | |
| 数据处理（1000点） | ≤ ___ ms | | |
| 单批落库（5000条） | ≤ ___ ms | | |
| 内存占用（稳态） | ≤ ___ MB | | |
| CPU 占用（稳态） | ≤ ___ % | | |

### 11. 性能调优检查清单

- [ ] 是否有忙等循环（无 Delay）？
- [ ] 轮询周期是否匹配设备响应时间（周期 > 总耗时 × 1.5）？
- [ ] 是否逐点读取而非批量？
- [ ] 是否逐条提交数据库而非批量？
- [ ] 是否有无界队列/缓冲？
- [ ] 高频路径是否产生大量临时对象？
- [ ] 是否有大对象分配（LOH）？
- [ ] 界面刷新率是否合理（≤30Hz）？
- [ ] 曲线是否按像素降采样？
- [ ] Pen/Brush/Font 是否缓存？
- [ ] 日志是否在高频路径做字符串拼接？
- [ ] lock 范围是否包住了 IO？
- [ ] 是否使用了 `ArrayPool` 复用缓冲？
- [ ] 查询是否走了索引？
- [ ] 是否有定时器重入？
- [ ] 长稳测试是否跑过 ≥72h？
