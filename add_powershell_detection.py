#!/usr/bin/env python3
"""添加 PowerShell GPU 检测作为备用方案"""

with open('igpu_burn_win.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 在 detect_all_gpus 函数开头添加备用检测
old_start = '''def detect_all_gpus() -> list:
    """
    检测系统所有 GPU，返回列表。
    每项: {vendor, name, type, encoder_h264, encoder_hevc, hwaccel, label}
    vendor: Intel / AMD / NVIDIA
    type: integrated / dedicated
    """
    gpus = []

    if IS_WINDOWS:'''

new_start = '''def detect_all_gpus() -> list:
    """
    检测系统所有 GPU，返回列表。
    每项: {vendor, name, type, encoder_h264, encoder_hevc, hwaccel, label}
    vendor: Intel / AMD / NVIDIA
    type: integrated / dedicated
    """
    gpus = []

    # ── 备用 GPU 检测：PowerShell (WMIC 失败时使用) ───────────────
    def powershell_detect_gpus():
        """使用 PowerShell 检测 GPU（WMIC 备用方案）"""
        try:
            ps_script = '''
            $gpuList = Get-CimInstance -ClassName Win32_VideoController | ForEach-Object {
                [PSCustomObject]@{
                    Name = $_.Name
                    AdapterCompatibility = $_.AdapterCompatibility
                    Status = $_.Status
                    DriverVersion = $_.DriverVersion
                }
            }
            $gpuList | ConvertTo-Json -Compress
            '''
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                import json
                data = json.loads(result.stdout)
                # 确保是列表格式
                if isinstance(data, dict):
                    data = [data]
                return [(g.get('Name', ''), g.get('AdapterCompatibility', '')) for g in data]
        except Exception as e:
            print(f"  ⚠️  PowerShell 检测也失败了: {e}")
        return []
    
    if IS_WINDOWS:
        # 先尝试 WMIC
        wmic_success = False'''

content = content.replace(old_start, new_start)

# 在 WMIC 失败后添加 PowerShell 备用
old_wmic_fail = '''        except Exception as e:
            print(f"  ❌ WMIC 检测失败: {type(e).__name__}: {e}")
            print(f"     💡 建议: 尝试以管理员身份运行，或检查 Windows 系统文件完整性")'''

new_wmic_fail = '''        except Exception as e:
            print(f"  ❌ WMIC 检测失败: {type(e).__name__}: {e}")
            print(f"     💡 尝试使用 PowerShell 备用检测...")
            
            # 使用 PowerShell 备用检测
            ps_gpus = powershell_detect_gpus()
            if ps_gpus:
                print(f"  📋 PowerShell 检测到 {len(ps_gpus)} 个 GPU:")
                for name, compat in ps_gpus:
                    if name:
                        print(f"     - {name} (compat={compat})")
                        gpu = _make_gpu_entry(name, compat)
                        if gpu:
                            gpus.append(gpu)
                            print(f"  ✅ PowerShell 检测到 GPU: {gpu['name']}")'''

content = content.replace(old_wmic_fail, new_wmic_fail)

with open('igpu_burn_win.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ PowerShell 备用检测已添加")
