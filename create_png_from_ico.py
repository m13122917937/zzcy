#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PIL import Image
import os

ico_path = "honor_logo.ico"
png_path = "honor_logo.png"

if os.path.exists(ico_path):
    try:
        img = Image.open(ico_path)
        img.save(png_path, "PNG")
        print(f"成功创建 {png_path}")
    except Exception as e:
        print(f"转换失败: {e}")
        print("将使用代码中的文字降级方案")
else:
    print(f"{ico_path} 不存在")
