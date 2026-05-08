#!/usr/bin/env python3
"""查看 CH347 库导出的函数"""
import subprocess

result = subprocess.run(
    ['nm', '-D', '/usr/lib/libch347.so'],
    capture_output=True,
    text=True
)

# 只导出 CH347 开头的函数
functions = []
for line in result.stdout.split('\n'):
    if 'CH347' in line and ' T ' in line:
        func_name = line.split()[-1]
        if func_name.startswith('CH347'):
            functions.append(func_name)

print(f"CH347 库导出的函数 (共 {len(functions)} 个):")
print("=" * 60)
for func in sorted(functions):
    print(f"  {func}")
