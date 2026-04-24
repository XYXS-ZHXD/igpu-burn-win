#!/usr/bin/env python3
"""添加 PowerShell GPU 检测作为备用方案"""

with open('igpu_burn_win.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 detect_all_gpus 函数开头添加备用检测函数定义
old_func_def = '''def detect_all_gpus() -> list:
    """
    检测系统所有 GPU，返回列表。
    每项: {vendor, name, type, encoder_h264, encoder_hevc, hwaccel, label}
    vendor: Intel / AMD / NVIDIA
    type: integrated / dedicated
    """
    gpus = []

    if IS_WINDOWS:'''

new_func_def = '''def detect_all_gpus() -> list:
    """
    检测系统所有 GPU，返回列表。
    每项: {vendor, name, type, encoder_h264, encoder_hevc, hwaccel, label}
    vendor: Intel / AMD / NVIDIA
    type: integrated / dedicated
    """
    gpus = []

    # ── PowerShell GPU 检测函数（WMIC 备用方案）────────────────────
    def powershell_detect_gpus():
        """使用 PowerShell 检测 GPU"""
        try:
            ps_script = (
                "Get-CimInstance -ClassName Win32_VideoController | "
                "Select-Object -ExpandProperty Name"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                names = [n.strip() for n in result.stdout.strip().splitlines() if n.strip()]
                print(f"  📋 PowerShell 检测到: {names}")
                return names
        except Exception as e:
            print(f"  ⚠️  PowerShell 检测失败: {e}")
        return []

    if IS_WINDOWS:'''

content = content.replace(old_func_def, new_func_def)

# 修改 WMIC 检测失败部分，添加 PowerShell 备用
old_wmic_except = '''        except Exception as e:
            print(f"  ❌ WMIC 检测失败: {type(e).__name__}: {e}")
            print(f"     💡 建议: 尝试以管理员身份运行，或检查 Windows 系统文件完整性")'''

new_wmic_except = '''        except Exception as e:
            print(f"  ❌ WMIC 检测失败: {type(e).__name__}: {e}")
            print(f"     💡 尝试使用 PowerShell 备用检测...")
            
            # 使用 PowerShell 备用检测
            ps_names = powershell_detect_gpus()
            if ps_names:
                for name in ps_names:
                    if name:
                        gpu = _make_gpu_entry(name, "")
                        if gpu:
                            gpus.append(gpu)
                            print(f"  ✅ PowerShell 检测到 GPU: {gpu['name']}")
            else:
                print(f"     💡 建议: 尝试以管理员身份运行，或检查 Windows 系统文件完整性")'''

content = content.replace(old_wmic_except, new_wmic_except)

with open('igpu_burn_win.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ PowerShell 备用检测已添加")
