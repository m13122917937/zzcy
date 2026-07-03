#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行 build.bat 的脚本"""
import subprocess
import sys
import os

print("="*60)
print("开始构建 Apple Query Tool")
print("="*60)
print()

# 设置 Python 路径
python_path = r"C:\Users\lenovo\.conda\envs\apple_code\python.exe"

if not os.path.exists(python_path):
    print(f"错误: Python 路径不存在: {python_path}")
    sys.exit(1)

print(f"使用 Python: {python_path}")
print()

# 构建命令
cmd = [
    python_path, "-m", "nuitka",
    "--standalone",
    "--onefile",
    "--enable-plugin=pyqt6",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=honor_logo.ico",
    "--include-data-file=honor_logo.ico=honor_logo.ico",
    "--include-data-file=honor_logo.png=honor_logo.png",
    "--include-package=curl_cffi",
    "--include-package=PIL",
    "--include-module=environment_config",
    "--output-filename=AppleQueryTool.exe",
    "--output-dir=dist",
    "--assume-yes-for-downloads",
    "--show-progress",
    "--show-modules",
    "main.py"
]

print("运行命令:")
print(" ".join(cmd))
print()
print("="*60)
print("构建中... (这可能需要几分钟时间)")
print("="*60)
print()

try:
    result = subprocess.run(cmd, shell=True)
    print()
    print("="*60)
    if result.returncode == 0:
        print("构建成功!")
        output_exe = os.path.join("dist", "AppleQueryTool.exe")
        if os.path.exists(output_exe):
            size = os.path.getsize(output_exe)
            print(f"输出文件: {output_exe}")
            print(f"文件大小: {size:,} 字节")
    else:
        print(f"构建失败! 返回码: {result.returncode}")
    print("="*60)
except KeyboardInterrupt:
    print("\n用户取消了构建")
except Exception as e:
    print(f"\n构建出错: {e}")
