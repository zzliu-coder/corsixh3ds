#!/usr/bin/env python3
"""Render artifacts/verification/summary.json as a readable Markdown report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


def yes_no(value: bool) -> str:
    return "通过" if value else "未执行"


def render(summary: dict) -> str:
    lines = [
        "# 虚拟机验证结果",
        "",
        f"- 平台：`{summary.get('platform')}`",
        f"- Python：`{summary.get('python')}`",
        f"- CMake：`{summary.get('cmake')}`",
        f"- GCC：`{summary.get('gcc')}`",
        f"- Clang：`{summary.get('clang') or '未安装'}`",
        "",
        "## 构建矩阵",
        "",
        "| 矩阵 | CTest 总数 | 失败 | 结果 |",
        "|---|---:|---:|---|",
    ]
    for matrix in summary.get("matrices", []):
        failed = matrix.get("ctest_failed")
        total = matrix.get("ctest_total")
        status = "通过" if failed == 0 and total is not None else "失败/未知"
        lines.append(f"| {matrix.get('name')} | {total} | {failed} | {status} |")

    lines.extend(
        [
            "",
            "## 自动化覆盖",
            "",
            f"- C++ 测试：{summary.get('cpp_tests')} 项，失败 {summary.get('cpp_failed')} 项。",
            f"- Python/Lua/静态测试：{summary.get('python_tests')} 项，跳过 {summary.get('python_skipped', 0)} 项。",
            f"- C++ 重复稳定性：{summary.get('repeat_count')} 轮。",
            f"- Shell 语法检查：{summary.get('shell_scripts_checked')} 个脚本。",
            f"- 固定提交/哈希清单：{'通过' if summary.get('pins_validated') else '未通过'}。",
            f"- 实际上游 Lua API 契约：{yes_no(bool(summary.get('actual_upstream_api_checked')))}。",
            f"- 双屏模拟器预览：`{summary.get('preview')}`。",
            "",
            "## 交叉编译与真机边界",
            "",
            f"- devkitARM `.3dsx` 交叉链接：{yes_no(bool(summary.get('true_3ds_cross_build_executed')))}。",
            f"- 交叉编译说明：{summary.get('cross_build_skip_reason') or '已执行'}。",
            f"- Old 3DS 真机测试：{yes_no(bool(summary.get('hardware_tests_executed')))}。",
            "",
            "3DS API 桩编译只能证明移植层使用的函数形状和 C++ 语法。最终链接、帧率、音频、合盖、HOME、SD 卡和内存稳定性仍以 Old 3DS 真机结果为准。",
            "",
            "## 模拟器输出 SHA-256",
            "",
        ]
    )
    for name, digest in sorted(summary.get("simulator_sha256", {}).items()):
        lines.append(f"- `{name}`：`{digest}`")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
