#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试修复的功能"""
import os
import sys

print("="*60)
print("测试修复内容")
print("="*60)

# 检查图标文件
print("\n1. 检查图标文件:")
icon_files = ['honor_logo.ico', 'honor_logo.png']
for f in icon_files:
    exists = os.path.exists(f)
    status = "✓ 存在" if exists else "✗ 不存在"
    size = os.path.getsize(f) if exists else 0
    print(f"   {f:20} {status} ({size} bytes)")

# 检查 build.bat
print("\n2. 检查 build.bat 配置:")
with open('build.bat', 'r', encoding='utf-8') as f:
    content = f.read()
    if 'honor_logo.png' in content:
        print("   ✓ build.bat 已包含 honor_logo.png")
    else:
        print("   ✗ build.bat 未包含 honor_logo.png")

# 检查 main.py 中的异常处理
print("\n3. 检查全局异常处理:")
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()
    if 'global_exception_handler' in content:
        print("   ✓ 已添加 global_exception_handler")
    else:
        print("   ✗ 未添加 global_exception_handler")

print("\n" + "="*60)
print("修复检查完成！")
print("="*60)
print("\n现在可以运行 build.bat 进行打包了！")
