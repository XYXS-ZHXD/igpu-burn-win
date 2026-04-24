#!/usr/bin/env python3
"""增强 GPU 检测逻辑"""

import re

with open('igpu_burn_win.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 增强 WMIC 错误处理
old_wmic = '''    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get",
                 "Name,AdapterCompatibility", "/format:csv"],
                text=True, timeout=10, stderr=subprocess.DEVNULL
            )
            lines = [l.strip() for l in out.splitlines()
                     if l.strip() and "Node" not in l and "Name" not in l]

            for line in lines:
                parts = line.split(",")
                if len(parts) >= 3:
                    compat = parts[1].lower()
                    name = parts[2].strip()

                    gpu = _make_gpu_entry(name, compat)
                    if gpu:
                        gpus.append(gpu)
        except Exception:
            pass'''

new_wmic = '''    if IS_WINDOWS:
        print("\\n  🔍 正在检测 GPU (使用 WMIC)...")
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get",
                 "Name,AdapterCompatibility", "/format:csv"],
                text=True, timeout=10, stderr=subprocess.STDOUT
            )
            lines = [l.strip() for l in out.splitlines()
                     if l.strip() and "Node" not in l and "Name" not in l]
            
            print(f"  📋 WMIC 原始输出 ({len(lines)} 行):")
            for i, line in enumerate(lines):
                print(f"     [{i}] {line[:80]}")

            for line in lines:
                parts = line.split(",")
                if len(parts) >= 3:
                    compat = parts[1].lower()
                    name = parts[2].strip()

                    gpu = _make_gpu_entry(name, compat)
                    if gpu:
                        gpus.append(gpu)
                        print(f"  ✅ 检测到 GPU: {gpu['name']} ({gpu['vendor']})")
                    else:
                        print(f"  ⚠️  未知 GPU: {name} (compat={compat})")
        except FileNotFoundError as e:
            print(f"  ❌ WMIC 命令未找到: {e}")
            print(f"     💡 建议: Windows 10/11 应包含 WMIC，可能被安全软件禁用")
        except subprocess.TimeoutExpired:
            print(f"  ❌ WMIC 命令超时")
        except Exception as e:
            print(f"  ❌ WMIC 检测失败: {type(e).__name__}: {e}")
            print(f"     💡 建议: 尝试以管理员身份运行，或检查 Windows 系统文件完整性")'''

content = content.replace(old_wmic, new_wmic)

# 2. 增强 GPU 检测失败诊断
old_detect_end = '''    return gpus'''

new_detect_end = '''    if not gpus:
        print("\\n  ❌ 未检测到任何支持的 GPU！")
        print(f"     可能原因:")
        print(f"       1. 显卡驱动未正确安装")
        print(f"       2. WMIC 命令执行失败")
        print(f"       3. 混合显卡环境识别问题")
        print(f"     建议操作:")
        print(f"       1. 打开设备管理器查看显卡状态")
        print(f"       2. 更新显卡驱动 (Intel/AMD/NVIDIA 官网)")
        print(f"       3. 以管理员身份运行程序")
        print(f"       4. 运行 'wmic path win32_VideoController get Name' 手动检测")
    
    return gpus'''

content = content.replace(old_detect_end, new_detect_end)

with open('igpu_burn_win.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ GPU 检测逻辑已增强")
