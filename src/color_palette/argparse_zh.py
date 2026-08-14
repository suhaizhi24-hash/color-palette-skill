from __future__ import annotations

import argparse
import re


class ChineseArgumentParser(argparse.ArgumentParser):
    """让 argparse 的内置帮助标题与常见错误保持中文。"""

    _HELP_REPLACEMENTS = {
        "usage:": "用法：",
        "positional arguments:": "位置参数：",
        "options:": "选项：",
        "optional arguments:": "选项：",
        "show this help message and exit": "显示帮助并退出",
    }

    def format_help(self) -> str:
        text = super().format_help()
        for source, target in self._HELP_REPLACEMENTS.items():
            text = text.replace(source, target)
        return text

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法：")

    def error(self, message: str) -> None:
        translated = self._translate_error(message)
        self.print_usage()
        self.exit(2, f"{self.prog}: 参数错误：{translated}\n")

    @staticmethod
    def _translate_error(message: str) -> str:
        prefixes = {
            "the following arguments are required: ": "缺少必需参数：",
            "unrecognized arguments: ": "无法识别的参数：",
        }
        for source, target in prefixes.items():
            if message.startswith(source):
                return target + message.removeprefix(source)
        match = re.fullmatch(r"argument (.+): expected one argument", message)
        if match:
            return f"参数{match.group(1)}需要一个值"
        match = re.fullmatch(r"argument (.+): invalid int value: (.+)", message)
        if match:
            return f"参数{match.group(1)}需要整数，收到：{match.group(2)}"
        match = re.fullmatch(
            r"argument (.+): invalid choice: (.+) \(choose from (.+)\)",
            message,
        )
        if match:
            return f"参数{match.group(1)}的值{match.group(2)}无效，可选值：{match.group(3)}"
        return "参数无效，请使用--help查看可用选项"
