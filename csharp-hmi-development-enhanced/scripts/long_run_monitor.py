#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长稳测试监控工具
自动监控目标进程的内存、句柄、CPU 使用率，持续 72 小时并生成报告

使用方法：
    python long_run_monitor.py --process-name "YourApp.exe" --duration 72

参数：
    --process-name: 被监控的进程名称（如 "MyHMI.exe"）
    --duration: 监控时长（小时），默认 72
    --interval: 采样间隔（秒），默认 60
    --output: 报告输出路径，默认当前目录
"""

import psutil
import time
import argparse
import csv
import json
from datetime import datetime, timedelta
import os
import sys

class LongRunMonitor:
    def __init__(self, process_name, duration_hours=72, interval_seconds=60, output_dir="."):
        self.process_name = process_name
        self.duration_hours = duration_hours
        self.interval_seconds = interval_seconds
        self.output_dir = output_dir
        
        self.process = None
        self.samples = []
        self.start_time = None
        self.end_time = None
        
    def find_process(self):
        """查找目标进程"""
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'].lower() == self.process_name.lower():
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None
    
    def collect_sample(self):
        """采集一次样本"""
        if self.process is None or not self.process.is_running():
            print(f"[{datetime.now()}] 进程已退出")
            return None
        
        try:
            # 内存信息
            mem_info = self.process.memory_info()
            mem_percent = self.process.memory_percent()
            
            # CPU 使用率（需要间隔采样）
            cpu_percent = self.process.cpu_percent(interval=1)
            
            # 句柄数（Windows）
            try:
                num_handles = self.process.num_handles()
            except AttributeError:
                # Linux/Mac 用文件描述符数量
                num_handles = self.process.num_fds()
            
            # 线程数
            num_threads = self.process.num_threads()
            
            sample = {
                'timestamp': datetime.now().isoformat(),
                'elapsed_hours': (datetime.now() - self.start_time).total_seconds() / 3600,
                'memory_mb': mem_info.rss / 1024 / 1024,
                'memory_percent': mem_percent,
                'cpu_percent': cpu_percent,
                'num_handles': num_handles,
                'num_threads': num_threads
            }
            
            self.samples.append(sample)
            return sample
            
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print(f"[{datetime.now()}] 采样失败: {e}")
            return None
    
    def run(self):
        """开始监控"""
        print(f"正在查找进程: {self.process_name}")
        self.process = self.find_process()
        
        if self.process is None:
            print(f"错误: 未找到进程 '{self.process_name}'")
            print("提示: 请先启动被测程序，然后再运行本监控工具")
            sys.exit(1)
        
        print(f"找到进程: PID={self.process.pid}")
        print(f"监控时长: {self.duration_hours} 小时")
        print(f"采样间隔: {self.interval_seconds} 秒")
        print(f"预计采样次数: {int(self.duration_hours * 3600 / self.interval_seconds)}")
        print(f"开始时间: {datetime.now()}")
        print("-" * 60)
        
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(hours=self.duration_hours)
        
        sample_count = 0
        
        try:
            while datetime.now() < self.end_time:
                sample = self.collect_sample()
                
                if sample is None:
                    print("进程已退出，监控终止")
                    break
                
                sample_count += 1
                
                # 每 10 次采样打印一次进度
                if sample_count % 10 == 0:
                    elapsed = datetime.now() - self.start_time
                    remaining = self.end_time - datetime.now()
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                          f"已运行 {elapsed}, 剩余 {remaining} | "
                          f"内存: {sample['memory_mb']:.1f} MB, "
                          f"CPU: {sample['cpu_percent']:.1f}%, "
                          f"句柄: {sample['num_handles']}")
                
                # 实时保存（每 100 次）
                if sample_count % 100 == 0:
                    self.save_intermediate_results()
                
                # 等待下次采样
                time.sleep(self.interval_seconds)
                
        except KeyboardInterrupt:
            print("\n用户中断监控")
        
        print("-" * 60)
        print(f"监控结束时间: {datetime.now()}")
        print(f"实际监控时长: {(datetime.now() - self.start_time).total_seconds() / 3600:.2f} 小时")
        print(f"总采样次数: {len(self.samples)}")
        
        # 生成最终报告
        self.generate_report()
    
    def save_intermediate_results(self):
        """保存中间结果（防止崩溃丢失数据）"""
        csv_file = os.path.join(self.output_dir, f"{self.process_name}_samples.csv")
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            if self.samples:
                writer = csv.DictWriter(f, fieldnames=self.samples[0].keys())
                writer.writeheader()
                writer.writerows(self.samples)
    
    def generate_report(self):
        """生成测试报告"""
        if not self.samples:
            print("无有效样本，无法生成报告")
            return
        
        # 保存 CSV
        csv_file = os.path.join(self.output_dir, f"{self.process_name}_samples.csv")
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=self.samples[0].keys())
            writer.writeheader()
            writer.writerows(self.samples)
        print(f"✓ 已保存样本数据: {csv_file}")
        
        # 统计分析
        memory_values = [s['memory_mb'] for s in self.samples]
        handle_values = [s['num_handles'] for s in self.samples]
        cpu_values = [s['cpu_percent'] for s in self.samples]
        
        initial_memory = memory_values[0]
        final_memory = memory_values[-1]
        memory_growth = final_memory - initial_memory
        memory_growth_percent = (memory_growth / initial_memory) * 100 if initial_memory > 0 else 0
        
        initial_handles = handle_values[0]
        final_handles = handle_values[-1]
        handle_growth = final_handles - initial_handles
        
        report = {
            'process_name': self.process_name,
            'start_time': self.start_time.isoformat(),
            'end_time': datetime.now().isoformat(),
            'duration_hours': (datetime.now() - self.start_time).total_seconds() / 3600,
            'sample_count': len(self.samples),
            
            'memory': {
                'initial_mb': initial_memory,
                'final_mb': final_memory,
                'peak_mb': max(memory_values),
                'average_mb': sum(memory_values) / len(memory_values),
                'growth_mb': memory_growth,
                'growth_percent': memory_growth_percent
            },
            
            'handles': {
                'initial': initial_handles,
                'final': final_handles,
                'peak': max(handle_values),
                'average': sum(handle_values) / len(handle_values),
                'growth': handle_growth
            },
            
            'cpu': {
                'peak_percent': max(cpu_values),
                'average_percent': sum(cpu_values) / len(cpu_values),
                'min_percent': min(cpu_values)
            },
            
            'verdict': self.get_verdict(memory_growth_percent, handle_growth)
        }
        
        # 保存 JSON 报告
        json_file = os.path.join(self.output_dir, f"{self.process_name}_report.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"✓ 已保存 JSON 报告: {json_file}")
        
        # 生成 Markdown 报告
        md_file = os.path.join(self.output_dir, f"{self.process_name}_report.md")
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(self.format_markdown_report(report))
        print(f"✓ 已保存 Markdown 报告: {md_file}")
        
        # 打印摘要
        print("\n" + "=" * 60)
        print("长稳测试报告摘要")
        print("=" * 60)
        print(f"进程名称: {self.process_name}")
        print(f"测试时长: {report['duration_hours']:.2f} 小时")
        print(f"采样次数: {report['sample_count']}")
        print("-" * 60)
        print(f"内存初始值: {initial_memory:.1f} MB")
        print(f"内存最终值: {final_memory:.1f} MB")
        print(f"内存峰值: {report['memory']['peak_mb']:.1f} MB")
        print(f"内存增长: {memory_growth:.1f} MB ({memory_growth_percent:.2f}%)")
        print("-" * 60)
        print(f"句柄初始值: {initial_handles}")
        print(f"句柄最终值: {final_handles}")
        print(f"句柄峰值: {report['handles']['peak']}")
        print(f"句柄增长: {handle_growth}")
        print("-" * 60)
        print(f"CPU 平均占用: {report['cpu']['average_percent']:.1f}%")
        print(f"CPU 峰值: {report['cpu']['peak_percent']:.1f}%")
        print("=" * 60)
        print(f"测试结论: {report['verdict']['result']}")
        print(f"详细说明: {report['verdict']['reason']}")
        print("=" * 60)
    
    def get_verdict(self, memory_growth_percent, handle_growth):
        """判定测试结果"""
        issues = []
        
        # 内存增长 > 5% 视为泄漏
        if memory_growth_percent > 5:
            issues.append(f"内存增长 {memory_growth_percent:.2f}% 超过阈值 5%")
        
        # 句柄增长 > 10% 视为泄漏
        if handle_growth > 100 or (handle_growth > 10 and handle_growth / max(self.samples[0]['num_handles'], 1) > 0.1):
            issues.append(f"句柄增长 {handle_growth} 可能存在泄漏")
        
        if issues:
            return {
                'result': '❌ 未通过',
                'reason': '; '.join(issues)
            }
        else:
            return {
                'result': '✅ 通过',
                'reason': '内存增长 < 5%，句柄无泄漏，符合长稳要求'
            }
    
    def format_markdown_report(self, report):
        """格式化 Markdown 报告"""
        md = f"""# 长稳测试报告 - {report['process_name']}

## 测试信息

- **进程名称**: {report['process_name']}
- **开始时间**: {report['start_time']}
- **结束时间**: {report['end_time']}
- **测试时长**: {report['duration_hours']:.2f} 小时
- **采样次数**: {report['sample_count']}

## 内存分析

| 指标 | 数值 |
|---|---|
| 初始内存 | {report['memory']['initial_mb']:.1f} MB |
| 最终内存 | {report['memory']['final_mb']:.1f} MB |
| 峰值内存 | {report['memory']['peak_mb']:.1f} MB |
| 平均内存 | {report['memory']['average_mb']:.1f} MB |
| 内存增长 | {report['memory']['growth_mb']:.1f} MB ({report['memory']['growth_percent']:.2f}%) |

**判定标准**: 内存增长 < 5% 为合格

## 句柄分析

| 指标 | 数值 |
|---|---|
| 初始句柄数 | {report['handles']['initial']} |
| 最终句柄数 | {report['handles']['final']} |
| 峰值句柄数 | {report['handles']['peak']} |
| 平均句柄数 | {report['handles']['average']:.0f} |
| 句柄增长 | {report['handles']['growth']} |

**判定标准**: 无明显增长趋势

## CPU 使用率

| 指标 | 数值 |
|---|---|
| 平均 CPU | {report['cpu']['average_percent']:.1f}% |
| 峰值 CPU | {report['cpu']['peak_percent']:.1f}% |
| 最低 CPU | {report['cpu']['min_percent']:.1f}% |

## 测试结论

**{report['verdict']['result']}**

{report['verdict']['reason']}

## 数据文件

- 样本数据: `{self.process_name}_samples.csv`
- JSON 报告: `{self.process_name}_report.json`

---

*报告生成时间: {datetime.now().isoformat()}*
"""
        return md

def main():
    parser = argparse.ArgumentParser(description='上位机程序长稳测试监控工具')
    parser.add_argument('--process-name', required=True, help='被监控的进程名称（如 MyHMI.exe）')
    parser.add_argument('--duration', type=float, default=72, help='监控时长（小时），默认 72')
    parser.add_argument('--interval', type=int, default=60, help='采样间隔（秒），默认 60')
    parser.add_argument('--output', default='.', help='报告输出目录，默认当前目录')
    
    args = parser.parse_args()
    
    # 创建输出目录
    os.makedirs(args.output, exist_ok=True)
    
    # 开始监控
    monitor = LongRunMonitor(
        process_name=args.process_name,
        duration_hours=args.duration,
        interval_seconds=args.interval,
        output_dir=args.output
    )
    
    monitor.run()

if __name__ == '__main__':
    main()
