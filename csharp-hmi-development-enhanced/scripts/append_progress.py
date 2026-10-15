#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
append_progress.py — 向开发进度日志追加一条记录（进度落盘机制的命令行封装）

用法：
    python append_progress.py <docs目录> "<轮次标题>" \
        --goal "本次目标" \
        --done "完成内容1; 完成内容2" \
        --files "path/a.cs; path/b.cs" \
        --decisions "决策1及理由; 决策2及理由" \
        --next "遗留问题1; 下一步动作" \
        --sync "已同步 02 文档第 3.2 节"

    # 若 docs 目录不存在会自动创建并生成日志骨架
    python append_progress.py ./MyProject/docs "完成 Modbus 实现" \
        --goal "实现 Modbus RTU 协议层" \
        --done "实现 CRC16; 实现地址归并规划器" \
        --next "待客户确认字节序"

设计原则：
    - 追加式：绝不覆盖历史内容
    - 强制：目标/完成内容/下一步 为必填（防止只写"已完成"）
    - 简洁：一行命令完成落盘
"""

import argparse
import os
import sys
from datetime import datetime

LOG_NAME = "05-开发进度日志.md"

HEADER = """# 开发进度日志

> ⚠️ 本文件为**追加式**记录，**禁止覆盖历史内容**。
> 每当完成一个有实质产出的对话轮次，必须追加一条记录。

## 日志格式约定

每条记录包含：时间戳 / 本次目标 / 完成内容 / 产出文件 / 关键决策及理由 / 遗留问题下一步

**禁止**只写"已完成"。必须写清：完成了什么、在哪、依据是什么。
**必须**记录"关键决策及理由"——三个月后回头看，理由比结论重要。
**必须**写"遗留问题 / 下一步"——这是下次对话的上下文入口。

---
"""


def split_items(text):
    """支持 ; ； 换行 三种分隔"""
    if not text:
        return []
    for sep in ("；", ";", "\n"):
        text = text.replace(sep, "|")
    return [x.strip() for x in text.split("|") if x.strip()]


def build_entry(title, goal, done, files, decisions, nextstep, sync):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append("")
    lines.append(f"## [{ts}] {title}")
    lines.append("")
    lines.append(f"- **本次目标**：{goal}")

    done_items = split_items(done)
    if len(done_items) <= 1:
        lines.append(f"- **完成内容**：{done_items[0] if done_items else goal}")
    else:
        lines.append("- **完成内容**：")
        for item in done_items:
            lines.append(f"  - {item}")

    file_items = split_items(files)
    if file_items:
        if len(file_items) == 1:
            lines.append(f"- **产出文件**：`{file_items[0]}`")
        else:
            lines.append("- **产出文件**：")
            for f in file_items:
                lines.append(f"  - `{f}`")

    dec_items = split_items(decisions)
    if dec_items:
        if len(dec_items) == 1:
            lines.append(f"- **关键决策及理由**：{dec_items[0]}")
        else:
            lines.append("- **关键决策及理由**：")
            for d in dec_items:
                lines.append(f"  - {d}")

    next_items = split_items(nextstep)
    if next_items:
        if len(next_items) == 1:
            lines.append(f"- **遗留问题 / 下一步**：{next_items[0]}")
        else:
            lines.append("- **遗留问题 / 下一步**：")
            for n in next_items:
                lines.append(f"  - {n}")

    if sync:
        lines.append(f"- **文档同步**：{sync}")

    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="向开发进度日志追加一条记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='示例：python append_progress.py ./docs "完成通信层" '
               '--goal "实现三层抽象" --done "定义接口; 实现 SerialTransport" '
               '--next "待确认波特率"'
    )
    parser.add_argument("docs_dir", help="docs 目录（或项目根目录）")
    parser.add_argument("title", help="本轮次标题")
    parser.add_argument("--goal", required=True, help="本次目标（必填）")
    parser.add_argument("--done", required=True, help="完成内容（必填，用 ; 分隔多项）")
    parser.add_argument("--files", default="", help="产出文件（用 ; 分隔）")
    parser.add_argument("--decisions", default="", help="关键决策及理由（用 ; 分隔）")
    parser.add_argument("--next", dest="nextstep", required=True,
                        help="遗留问题 / 下一步（必填，用 ; 分隔）")
    parser.add_argument("--sync", default="", help="文档同步说明")
    args = parser.parse_args()

    # 定位 docs 目录
    docs_dir = args.docs_dir
    if os.path.basename(os.path.normpath(docs_dir)) != "docs":
        # 传入的是项目根目录
        candidate = os.path.join(docs_dir, "docs")
        if os.path.isdir(candidate) or not os.path.exists(os.path.join(docs_dir, LOG_NAME)):
            docs_dir = candidate

    os.makedirs(docs_dir, exist_ok=True)
    log_path = os.path.join(docs_dir, LOG_NAME)

    # 文件不存在则先写骨架
    if not os.path.exists(log_path):
        with open(log_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(HEADER)
        print(f"[NEW] 已创建日志文件：{log_path}")

    entry = build_entry(
        args.title, args.goal, args.done,
        args.files, args.decisions, args.nextstep, args.sync
    )

    # 追加（使用 newline="" 避免 Windows 下产生额外换行）
    with open(log_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(entry)

    print(f"[OK] 已追加进度记录")
    print(f"     文件：{os.path.abspath(log_path)}")
    print(f"     标题：{args.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
