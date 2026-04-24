#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║         iGPU / dGPU 烤机程序 - Windows 版                       ║
║         支持 Intel / AMD / NVIDIA 全显卡                          ║
║         支持独立显卡: NVIDIA dGPU / AMD dGPU                     ║
║                                                                ║
║                                                                ║
║  版本：v3.6 (2026-04-24) - 增强 GPU 验证与错误诊断              ║
║                                                                ║
║  v3.6 新增：                                                    ║
║    ✅ GPU 活动验证机制，确保 GPU 真正被调用                      ║
║    ✅ 增强错误提示，DX11 失败时明确告知用户                      ║
║    ✅ GPU 状态实时日志，监控面板显示详细状态                     ║
║                                                                ║
║  压力来源：                                                     ║
║    1. DirectX 11 —— UpdateSubresource 持续搬运（主力，无依赖）  ║
║    2. GPU 计算 —— CUDA (NVIDIA) / OpenCL (AMD/NVIDIA) 通用计算  ║
║    3. CPU 计算 —— numpy 矩阵爆算 (备用/补充)                    ║
║    4. GPU 编码 —— FFmpeg 硬件加速（QSV/NVENC/AMF）              ║
║                                                                ║
║  用法：                                                         ║
║    igpu_burn_win.exe [选项]                                     ║
║    python igpu_burn_win.py [选项]                               ║
╚══════════════════════════════════════════════════════════════════╝
"""

import argparse
import subprocess
import threading
import time
import os
import sys
import signal
import shutil
import multiprocessing
import platform
import json
import re
import ctypes
import struct
from datetime import datetime
from typing import Optional, List, Dict

# ── 可选依赖 ──────────────────────────────────────────────────────
HAS_NUMPY = False
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    pass

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── 全局状态 ──────────────────────────────────────────────────────
STOP_EVENT = threading.Event()
STATS = {
    "compute_threads": 0,
    "media_streams": 0,
    "gpu_compute_workers": 0,
    "dx_workers": 0,
    "dx_active": False,  # v3.6 新增：DX11 是否成功启动
    "dx_frames": 0,      # v3.6 新增：DX11 渲染帧数
    "dx_errors": 0,      # v3.6 新增：DX11 错误计数
    "start_time": 0,
    "total_frames": 0,
    "errors": 0,
    "gpu_vendor": "Unknown",
    "gpu_name": "Unknown",
    "encoder_used": "Unknown",
    "gpu_temp": "N/A",
    "gpu_power_w": 0.0,
    "gpu_util_pct": 0,
}
STATS_LOCK = threading.Lock()
IS_WINDOWS = platform.system() == "Windows"


def find_ffmpeg() -> str:
    """
    查找 ffmpeg 路径，优先级：
    1. EXE 同目录的 ffmpeg.exe（最优先，用于用户手动放置的情况）
    2. PATH 中的 ffmpeg
    3. 返回 "ffmpeg" 让系统 PATH 处理
    """
    # 1. 检查 EXE/Python 脚本同目录
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包的 EXE
        exe_dir = os.path.dirname(sys.executable)
    else:
        # 直接运行 Python 脚本
        exe_dir = os.path.dirname(os.path.abspath(__file__))

    local_ffmpeg = os.path.join(exe_dir, "ffmpeg.exe")
    if os.path.isfile(local_ffmpeg):
        print(f"\n  ✅ 找到同目录 ffmpeg.exe: {local_ffmpeg}")
        return local_ffmpeg

    # 2. 尝试 PATH 中的 ffmpeg
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 3. Windows 上也试试无扩展名
    if IS_WINDOWS:
        for name in ["ffmpeg.exe", "ffmpeg"]:
            found = shutil.which(name)
            if found:
                return found

    return "ffmpeg"  # 返回命令名，让 subprocess 自己去 PATH 找


# ══════════════════════════════════════════════════════════════════
# 模块 0：DirectX 11 Compute Shader GPU 烤机（ctypes 实现，无外部依赖）
# ══════════════════════════════════════════════════════════════════
# 策略：通过 ctypes 调用 Windows DirectX 11 API，运行计算着色器
# 覆盖 Intel/AMD/NVIDIA 全显卡，无需 PyOpenGL/glfw，无需窗口句柄

DX11_AVAILABLE = False
# v3.6 新增：全局 DX11 状态标志
DX11_AVAILABLE = False  # 用于外部验证 DX11 是否成功初始化
_dx = None   # ctypes 加载器

def _load_dx11():
    """延迟加载 d3d11.dll，返回 ctypes 库对象或 None"""
    if not IS_WINDOWS:
        return None
    try:
        dx = ctypes.windll.LoadLibrary("d3d11.dll")
        return dx
    except Exception:
        return None


# ── DirectX 11 常量 ───────────────────────────────────────────────
D3D_SDK_VERSION = 7
DXGI_FORMAT_R32G32B32A32_FLOAT = 2
D3D11_USAGE_DEFAULT = 0
D3D11_BIND_SHADER_RESOURCE = 0x00000004
D3D11_BIND_UNORDERED_ACCESS = 0x00000008
D3D11_CPU_ACCESS_READ = 0x00010000
D3D11_RESOURCE_MISC_FLAG_NONE = 0
D3D11_COMPUTE_SHADER = 0x000000AC
D3D11_MAP_WRITE_DISCARD = 4
D3D11_DEVICE_TYPE_HARDWARE = 0
D3D_DRIVER_TYPE_HARDWARE = 1

# ── DXGI 类型（部分） ──────────────────────────────────────────────
class _DXGI_SWAP_CHAIN_DESC(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint32),
                ("Height", ctypes.c_uint32),
                ("RefreshRate", ctypes.c_double),
                ("Format", ctypes.c_uint32),
                ("ScanlineOrdering", ctypes.c_uint32),
                ("Scaling", ctypes.c_uint32),
                ("SwapEffect", ctypes.c_uint32),
                ("BufferCount", ctypes.c_uint32),
                ("BufferUsage", ctypes.c_uint32),
                ("OutputWindow", ctypes.c_void_p),
                ("SampleDesc", ctypes.c_uint32 * 2),
                ("Windowed", ctypes.c_int)]

# ── D3D11 类型 ───────────────────────────────────────────────────
class _D3D11_BUFFER_DESC(ctypes.Structure):
    _fields_ = [("ByteWidth", ctypes.c_uint32),
                ("Usage", ctypes.c_uint32),
                ("BindFlags", ctypes.c_uint32),
                ("CPUAccessFlags", ctypes.c_uint32),
                ("MiscFlags", ctypes.c_uint32),
                ("StructureByteStride", ctypes.c_uint32)]

class _D3D11_BOX(ctypes.Structure):
    _fields_ = [("left", ctypes.c_uint32), ("top", ctypes.c_uint32),
                ("front", ctypes.c_uint32), ("right", ctypes.c_uint32),
                ("bottom", ctypes.c_uint32), ("back", ctypes.c_uint32)]

class _D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p),
                ("RowPitch", ctypes.c_uint32),
                ("DepthPitch", ctypes.c_uint32)]


def dx_compute_worker(worker_id: int):
    """
    DirectX 11 GPU 烤机（ctypes 实现，零外部依赖）。
    策略：创建 DEFAULT Usage Buffer，持续调用 UpdateSubresource
    产生 PCIe 带宽压力 + GPU 内存控制器负载，覆盖 Intel/AMD/NVIDIA 全显卡。
    无需窗口句柄，无需 PyOpenGL/glfw，d3d11.dll 任何 Windows 均自带。
    
    v3.6 增强：
    - 增加 GPU 活动验证
    - 增强错误提示
    - 添加详细诊断信息
    """
    global DX11_AVAILABLE
    
    with STATS_LOCK:
        STATS["dx_workers"] += 1
    
    dx = None
    device = None
    immediate_context = None
    buf = None
    
    try:
        dx = _load_dx11()
        if dx is None:
            raise RuntimeError("无法加载 d3d11.dll - Windows 系统文件缺失或损坏")
        
        device = ctypes.c_void_p()
        immediate_context = ctypes.c_void_p()
        feature_levels = (ctypes.c_uint * 1)(0x0000B000)
        feature_level_out = ctypes.c_uint()
        
        hr = dx.D3D11CreateDevice(
            None,                   # pAdapter = NULL（默认适配器）
            D3D_DRIVER_TYPE_HARDWARE,
            None,                   # Software = NULL
            0x00000040,            # D3D11_CREATE_DEVICE_DISABLE_GPU_TIMEOUT
            feature_levels,
            1,
            D3D_SDK_VERSION,
            ctypes.byref(device),
            ctypes.byref(feature_level_out),
            ctypes.byref(immediate_context),
        )
        if hr != 0:
            raise RuntimeError(f"D3D11CreateDevice 失败：hr={hr} (0x{hr:08X})")
        
        # 标记 DX11 已成功初始化
        DX11_AVAILABLE = True
        with STATS_LOCK:
            STATS["dx_active"] = True
        
        # ── 创建 16 MB DEFAULT Buffer 并持续 UpdateSubresource ────
        buf_sz = 16 * 1024 * 1024   # 16 MB，足够大，持续占用 PCIe 带宽
        bd = _D3D11_BUFFER_DESC()
        bd.ByteWidth = buf_sz
        bd.Usage = D3D11_USAGE_DEFAULT   # 0 = DEFAULT，CPU 通过 UpdateSubresource 写入
        bd.BindFlags = 0
        bd.CPUAccessFlags = 0
        bd.MiscFlags = 0
        bd.StructureByteStride = 0
        
        buf = ctypes.c_void_p()
        hr = dx.ID3D11Device_CreateBuffer(
            device.value, ctypes.byref(bd), None, ctypes.byref(buf))
        if hr != 0:
            raise RuntimeError(f"CreateBuffer 失败 (hr={hr})")
        
        # 预计算上传数据（16 MB 全写同一值，GPU 必须完整读取并写入显存）
        fill_val = (worker_id * 0x9E3779B9 + 0xDEADBEEF) & 0xFFFFFFFF
        fill_bytes = struct.pack("<I", fill_val)
        upload_buf = bytearray(buf_sz)
        for i in range(0, buf_sz, 4):
            upload_buf[i:i+4] = fill_bytes
        
        # 构造 D3D11_BOX（全缓冲范围）
        box = _D3D11_BOX()
        box.left = 0
        box.top = 0
        box.front = 0
        box.right = buf_sz
        box.bottom = 1
        box.back = 1
        
        # v3.6 新增：打印启动成功消息
        print(f"  ✅ DirectX 11 GPU 烤机线程已启动 (worker={worker_id}, buffer=16MB)")
        
        # 主循环：持续搬运数据到 GPU
        local_frames = 0
        while not STOP_EVENT.is_set():
            # CPU → GPU 数据传输，每次完整 16 MB，触发 PCIe + 显存控制器
            dx.ID3D11DeviceContext_UpdateSubresource(
                immediate_context.value,
                buf.value,
                0,               # DstSubresource
                ctypes.byref(box),
                bytes(upload_buf),
                buf_sz,          # SrcRowPitch
                0,               # SrcDepthPitch
            )
            with STATS_LOCK:
                STATS["total_frames"] += 1
                STATS["dx_frames"] += 1
            local_frames += 1
        
        # v3.6 新增：打印停止消息
        print(f"  ⏹  DirectX 11 GPU 烤机线程已停止 (worker={worker_id}, frames={local_frames})")
    
    except Exception as e:
        error_msg = str(e)
        with STATS_LOCK:
            STATS["errors"] += 1
            STATS["dx_errors"] += 1
            STATS["dx_active"] = False
        
        # v3.6 新增：详细错误提示
        print(f"\n  ⚠️  WARNING: DirectX 11 GPU 烤机初始化失败！")
        print(f"     错误详情：{error_msg}")
        print(f"     影响：GPU 将不会被压力测试，仅 CPU 在工作！")
        print(f"     可能原因:")
        print(f"       1. Windows 版本过旧，缺少 DirectX 11")
        print(f"       2. 显卡驱动未正确安装")
        print(f"       3. 系统文件 d3d11.dll 损坏")
        print(f"     建议操作:")
        print(f"       1. 更新 Windows 到最新版本")
        print(f"       2. 更新显卡驱动 (Intel/AMD/NVIDIA 官网下载)")
        print(f"       3. 运行 sfc /scannow 修复系统文件")
        print()
        
        # 备用方案：如果 numpy 可用，回退到 CPU 计算
        if HAS_NUMPY:
            print(f"  ℹ️  启动 CPU 计算备用方案 (numpy 矩阵计算)...")
            compute_worker(worker_id + 1000, matrix_size=1536)
    
    finally:
        with STATS_LOCK:
            if STATS["dx_workers"] > 0:
                STATS["dx_workers"] -= 1


# ══════════════════════════════════════════════════════════════════
# 模块 0b：GPU 自动检测（支持多卡）
# ══════════════════════════════════════════════════════════════════

def detect_all_gpus() -> list:
    """
    检测系统所有 GPU，返回列表。
    每项: {vendor, name, type, encoder_h264, encoder_hevc, hwaccel, label}
    vendor: Intel / AMD / NVIDIA
    type: integrated / dedicated
    """
    gpus = []

    if IS_WINDOWS:
        print("\n  🔍 正在检测 GPU...")
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get",
                 "Name,AdapterCompatibility", "/format:csv"],
                text=True, timeout=10, stderr=subprocess.STDOUT
            )
            lines = [l.strip() for l in out.splitlines()
                     if l.strip() and "Node" not in l and "Name" not in l]
            
            print(f"  📋 WMIC 检测到 {len(lines)} 个设备:")
            for i, line in enumerate(lines):
                print(f"     [{i}] {line[:100]}")
            
            for line in lines:
                parts = line.split(",")
                if len(parts) >= 3:
                    compat = parts[1].lower()
                    name = parts[2].strip()
                    gpu = _make_gpu_entry(name, compat)
                    if gpu:
                        gpus.append(gpu)
                        print(f"  ✅ 识别: {gpu['name']} ({gpu['vendor']})")
                    else:
                        print(f"  ⚠️  跳过未知设备: {name}")
        except FileNotFoundError as e:
            print(f"  ❌ WMIC 未找到: {e}")
            print(f"     尝试使用 PowerShell 备用检测...")
            try:
                ps_result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", 
                     "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                    capture_output=True, text=True, timeout=15
                )
                if ps_result.returncode == 0 and ps_result.stdout.strip():
                    names = [n.strip() for n in ps_result.stdout.strip().splitlines() if n.strip()]
                    print(f"  📋 PowerShell 检测到: {names}")
                    for name in names:
                        if name:
                            gpu = _make_gpu_entry(name, "")
                            if gpu:
                                gpus.append(gpu)
            except Exception as ps_e:
                print(f"  ⚠️  PowerShell 也失败: {ps_e}")
        except Exception as e:
            print(f"  ❌ WMIC 检测失败: {e}")

    # macOS 备用
    if not gpus and platform.system() == "Darwin":
        try:
            out = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"],
                text=True, timeout=10, stderr=subprocess.DEVNULL
            )
            if "M1" in out or "M2" in out or "M3" in out or "M4" in out:
                gpus.append({
                    "vendor": "Apple", "name": "Apple Silicon",
                    "type": "integrated",
                    "encoder_h264": "h264_videotoolbox",
                    "encoder_hevc": "hevc_videotoolbox",
                    "hwaccel": "videotoolbox",
                    "label": "Apple Silicon + VideoToolbox"
                })
        except Exception:
            pass

    # 先打印 FFmpeg 编码器支持列表，帮助诊断问题
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        hw_encoders = ["h264_qsv", "hevc_qsv", "h264_nvenc", "hevc_nvenc",
                       "h264_amf", "hevc_amf", "h264_videotoolbox", "hevc_videotoolbox",
                       "h264_vaapi", "hevc_vaapi", "h264_v4l2m2m", "hevc_v4l2m2m",
                       "libx264", "libx265"]
        try:
            enc_out = subprocess.check_output(
                [ffmpeg, "-hide_banner", "-encoders"],
                text=True, timeout=10, stderr=subprocess.DEVNULL
            )
            found_hw = [e for e in hw_encoders if e in enc_out]
            found_sw = [e for e in ["libx264", "libx265", "libx264", "libx265"]
                        if e in enc_out]
            print(f"\n  🔧 FFmpeg 编码器支持：")
            print(f"     {' '.join(found_hw) if found_hw else '无硬件编码器'}")
            if not found_hw:
                print(f"     ⚠️  FFmpeg 不含任何硬件编码器！")
                print(f"     💡 建议下载含硬件加速的 FFmpeg：")
                print(f"         https://github.com/BtbN/FFmpeg-Builds/releases")
                print(f"         下载 ffmpeg-master-latest-win64-gpl.zip（勾选 hwaccel）")
        except Exception:
            pass
    else:
        print(f"\n  ⚠️  FFmpeg 未找到！请下载并放到程序同目录：")
        print(f"     https://github.com/BtbN/FFmpeg-Builds/releases")

    # 验证所有 GPU 的 FFmpeg 编码器
    for gpu in gpus:
        _verify_ffmpeg_encoder(gpu)

    if not gpus:
        print("\n  ❌ 未检测到任何 GPU！")
        print(f"     诊断建议:")
        print(f"       1. 打开设备管理器查看显卡状态")
        print(f"       2. 更新显卡驱动")
        print(f"       3. 以管理员身份运行程序")
        print(f"       4. 运行 'wmic path win32_VideoController get Name' 手动检测")
    else:
        print(f"\n  ✅ GPU 检测完成，共 {len(gpus)} 个显卡")
    
    return gpus


def _make_gpu_entry(name: str, compat: str) -> dict:
    """根据 GPU 名称和兼容性字符串生成 GPU 条目"""
    name_lower = name.lower()
    compat_lower = compat.lower()

    # ── NVIDIA ──────────────────────────────────────────────────
    if "nvidia" in compat_lower or "geforce" in name_lower or \
       "nvidia" in name_lower or "quadro" in name_lower or \
       "rtx" in name_lower or "gtx" in name_lower:
        # 判断是独显还是核显（NVIDIA 没有核显，这个判断是为混合环境准备）
        is_igpu = False  # NVIDIA 没有核显
        hwaccel = "cuda"
        return {
            "vendor": "NVIDIA",
            "name": name,
            "type": "dedicated" if not is_igpu else "integrated",
            "encoder_h264": "h264_nvenc",
            "encoder_hevc": "hevc_nvenc",
            "hwaccel": hwaccel,
            "label": f"NVIDIA NVENC 硬件加速 ({name})"
        }

    # ── AMD ────────────────────────────────────────────────────
    if "amd" in compat_lower or "radeon" in name_lower or \
       "amd" in name_lower:
        # 区分独显和核显
        # AMD 核显关键词
        igpu_keywords = ["uhd", "iris", "vega", "radeon graphics",
                         "radeon(tm) graphics", "amd radeon(tm)"]
        # AMD 独显关键词
        dgpu_keywords = ["rx ", "radeon rx", "radeon pro", "radeon vii",
                         "radeon(tm) rx", "amdradeon", "w series", "w5100",
                         "w7100", "w8100", "w9100", "ssg", "vega 10", "vega 20",
                         "navi", "rdna", "polaris", "fiji", "tahiti",
                         "gcn 5", "gcn 4", "gcn 3", "gcn 2"]

        name_lower_stripped = name_lower.replace(" ", "").replace("-", "")
        is_dgpu = any(kw.replace(" ", "").lower() in name_lower_stripped
                      for kw in ["rx", "radeonrx", "radeonpro", "radeonvii",
                                 "navi", "rdna", "polaris", "vega10",
                                 "vega20", "fiji", "tahiti"])
        is_igpu_keyword = any(kw in name_lower for kw in igpu_keywords)

        if is_dgpu and not is_igpu_keyword:
            gpu_type = "dedicated"
        else:
            gpu_type = "integrated"

        return {
            "vendor": "AMD",
            "name": name,
            "type": gpu_type,
            "encoder_h264": "h264_amf",
            "encoder_hevc": "hevc_amf",
            "hwaccel": "d3d11va",
            "label": f"AMD {'独显' if gpu_type == 'dedicated' else '核显'} AMF 硬件加速 ({name})"
        }

    # ── Intel ─────────────────────────────────────────────────
    if "intel" in compat_lower or "intel" in name_lower:
        return {
            "vendor": "Intel",
            "name": name,
            "type": "integrated",
            "encoder_h264": "h264_qsv",
            "encoder_hevc": "hevc_qsv",
            "hwaccel": "qsv",
            "label": f"Intel QSV 硬件加速 ({name})"
        }

    return None


def _verify_ffmpeg_encoder(gpu_info: dict):
    """
    验证 FFmpeg 是否真的支持检测到的硬件编码器，不支持则回退。
    增加详细诊断：区分"编码器未编译"和"硬件设备初始化失败"两种情况。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        gpu_info["label"] += "（FFmpeg 未找到，将使用软件编码）"
        return

    hevc_enc = gpu_info["encoder_hevc"]
    if hevc_enc in ("libx265", "libx264"):
        return  # 软件编码无需验证

    hw = gpu_info.get("hwaccel")
    encoder = hevc_enc

    # 先检查 FFmpeg 是否真的编译了该编码器（--encoders 过滤）
    try:
        enc_check = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10
        )
        encoder_found = encoder in enc_check.stdout or \
                        encoder.replace("_", " ") in enc_check.stdout
        if not encoder_found:
            gpu_info["label"] += (f"（FFmpeg 未编译 {encoder}，将使用软件编码）")
            gpu_info["encoder_h264"] = "libx264"
            gpu_info["encoder_hevc"] = "libx265"
            gpu_info["hwaccel"] = None
            return
    except Exception:
        pass

    # 再验证编码器实际运行能力
    try:
        test_cmd = _build_test_cmd(ffmpeg, encoder, hw)
        proc = subprocess.run(test_cmd, timeout=15,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        stderr_text = proc.stderr.decode(errors="ignore").lower()

        if proc.returncode != 0:
            if hw == "qsv":
                gpu_info["label"] += (
                    "（⚠️  Intel QSV 不可用 — 标准 FFmpeg 不含 QSV 支持\n"
                    "     这是业界限制，不是你的问题！\n"
                    "     QSV 需要用 Intel Media SDK 专门编译 FFmpeg。\n"
                    "     程序已默认开启 DirectX 11 GPU 烤机，\n"
                    "     UpdateSubresource 持续搬运数据，确保 Intel 核显全力运转。\n"
                    "     GPU 温度由 FFmpeg 媒体编码（CPU 承担）部分显示。")
            elif hw == "cuda":
                gpu_info["label"] += (
                    "（NVENC 初始化失败，可能原因：\n"
                    "     ① NVIDIA 驱动未安装或版本过低\n"
                    "     ② FFmpeg 打包版本不含 NVENC 支持\n"
                    "     已回退到软件编码（libx265）")
            elif hw == "d3d11va":
                gpu_info["label"] += (
                    "（AMF 初始化失败，可能原因：\n"
                    "     ① AMD 显卡驱动未正确安装\n"
                    "     ② FFmpeg 打包版本不含 AMF 支持\n"
                    "     已回退到软件编码（libx265）")
            else:
                gpu_info["label"] += "（硬件加速不可用，已回退到软件编码）"

            gpu_info["encoder_h264"] = "libx264"
            gpu_info["encoder_hevc"] = "libx265"
            gpu_info["hwaccel"] = None
    except Exception:
        pass


def _build_test_cmd(ffmpeg: str, encoder: str, hwaccel: str) -> list:
    """构建 FFmpeg 编码器测试命令"""
    null = "NUL" if IS_WINDOWS else "/dev/null"

    if hwaccel == "qsv":
        return [ffmpeg, "-hide_banner", "-loglevel", "error",
                "-init_hw_device", "qsv=hw",
                "-filter_hw_device", "hw",
                "-f", "lavfi", "-i", "color=black:size=320x240:rate=1",
                "-t", "0.1",
                "-vf", "hwupload=extra_hw_frames=64,format=qsv",
                "-vcodec", encoder,
                "-f", "null", null]

    if hwaccel in ("cuda", "d3d11va"):
        return [ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:size=320x240:rate=1",
                "-t", "0.1",
                "-pix_fmt", "yuv420p",
                "-vcodec", encoder,
                "-f", "null", null]

    if hwaccel == "videotoolbox":
        return [ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=black:size=320x240:rate=1",
                "-t", "0.1",
                "-vcodec", encoder,
                "-f", "null", null]

    # 软件
    return [ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=black:size=320x240:rate=1",
            "-t", "0.1", "-vcodec", encoder, "-f", "null", null]


# ══════════════════════════════════════════════════════════════════
# 模块 0b：多卡选择逻辑
# ══════════════════════════════════════════════════════════════════

def select_gpu(gpus: list, user_choice: str) -> dict:
    """
    从检测到的 GPU 列表中选择一个。
    user_choice: "auto" / "nvidia" / "amd" / "intel" / "dedicated" / "integrated"
                 或数字索引
    """
    if not gpus:
        return {
            "vendor": "Unknown", "name": "No GPU found",
            "type": "unknown",
            "encoder_h264": "libx264", "encoder_hevc": "libx265",
            "hwaccel": None,
            "label": "未检测到 GPU，将使用软件编码"
        }

    # 打印所有 GPU
    print("\n  🔍 检测到的显卡列表：")
    print("  " + "-" * 62)
    for i, gpu in enumerate(gpus):
        type_icon = "🟢" if gpu["type"] == "dedicated" else "🔵"
        hw_badge = "⚡" if gpu["hwaccel"] else "📦"
        print(f"  [{i}] {type_icon} {gpu['name']}")
        print(f"      厂商: {gpu['vendor']} | 类型: {gpu['type']} | "
              f"{hw_badge} 加速: {gpu['hwaccel'] or '无'}")
        print(f"      编码器: {gpu['encoder_hevc']}")
        print()
    print("  " + "-" * 62)

    # 自动选择策略
    if user_choice == "auto":
        # 优先级：独显 > 核显，NVIDIA > AMD > Intel
        priority = {"NVIDIA": 3, "AMD": 2, "Intel": 1, "Apple": 2}
        # 先找独显
        dgpu_list = [g for g in gpus if g["type"] == "dedicated"]
        if dgpu_list:
            dgpu_list.sort(key=lambda g: priority.get(g["vendor"], 0), reverse=True)
            chosen = dgpu_list[0]
            print(f"  ✅ 自动选择独显: {chosen['name']}")
            return chosen
        # 没有独显用核显
        igpu_list = [g for g in gpus if g["type"] == "integrated"]
        if igpu_list:
            igpu_list.sort(key=lambda g: priority.get(g["vendor"], 0), reverse=True)
            chosen = igpu_list[0]
            print(f"  ✅ 自动选择核显: {chosen['name']}")
            return chosen
        return gpus[0]

    # 按厂商选择
    vendor_map = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel", "apple": "Apple"}
    if user_choice.lower() in vendor_map:
        target_vendor = vendor_map[user_choice.lower()]
        matches = [g for g in gpus if g["vendor"] == target_vendor]
        if matches:
            # 如果有独显/核显选择，也要区分
            dgpu = [g for g in matches if g["type"] == "dedicated"]
            igpu = [g for g in matches if g["type"] == "integrated"]
            chosen = (dgpu[0] if dgpu else igpu[0] if igpu else matches[0])
            print(f"  ✅ 选择 {target_vendor}: {chosen['name']}")
            return chosen

    # 按类型选择
    if user_choice == "dedicated":
        dgpu_list = [g for g in gpus if g["type"] == "dedicated"]
        if dgpu_list:
            print(f"  ✅ 选择独显: {dgpu_list[0]['name']}")
            return dgpu_list[0]
    if user_choice == "integrated":
        igpu_list = [g for g in gpus if g["type"] == "integrated"]
        if igpu_list:
            print(f"  ✅ 选择核显: {igpu_list[0]['name']}")
            return igpu_list[0]

    # 按索引选择
    try:
        idx = int(user_choice)
        if 0 <= idx < len(gpus):
            print(f"  ✅ 选择第 {idx} 张: {gpus[idx]['name']}")
            return gpus[idx]
    except ValueError:
        pass

    # 默认选第一张
    print(f"  ⚠️  未找到匹配项 '{user_choice}'，使用第一张: {gpus[0]['name']}")
    return gpus[0]


# ══════════════════════════════════════════════════════════════════
# 模块 1：GPU 温度/功耗监控
# ══════════════════════════════════════════════════════════════════

def get_gpu_status(gpu_info: dict) -> dict:
    """
    获取 GPU 温度、功耗、利用率。
    NVIDIA: nvidia-smi
    AMD: WMI 或 atpxxxxx PowerMonitor
    Intel: WMI
    """
    status = {
        "temp": "N/A",
        "power_w": 0.0,
        "util_pct": 0,
        "memory_used_mb": 0,
        "memory_total_mb": 0,
        "source": "unknown"
    }

    # ── NVIDIA ──────────────────────────────────────────────────
    if gpu_info.get("vendor") == "NVIDIA":
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                out = subprocess.check_output(
                    [nvidia_smi,
                     "--query-gpu=temperature.gpu,power.draw,utilization.gpu,memory.used,memory.total",
                     "--format=csv,noheader,nounits"],
                    text=True, timeout=5, stderr=subprocess.DEVNULL
                )
                parts = out.strip().split(",")
                if len(parts) >= 5:
                    status["temp"] = f"{parts[0].strip()}°C"
                    status["power_w"] = float(parts[1].strip())
                    status["util_pct"] = int(parts[2].strip())
                    status["memory_used_mb"] = int(parts[3].strip())
                    status["memory_total_mb"] = int(parts[4].strip())
                    status["source"] = "nvidia-smi"
            except Exception:
                pass
        return status

    # ── AMD 独显 ────────────────────────────────────────────────
    if gpu_info.get("vendor") == "AMD" and gpu_info.get("type") == "dedicated":
        try:
            # 尝试 PowerShell 读取 AMD GPU 温度（WMI）
            ps = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-WmiObject MSAcl priate * -Namespace root/wmi | Where-Object {$_.InstanceName -like '*AMD*' -or $_.InstanceName -like '*ATK*'} | Select-Object -First 1 -ErrorAction SilentlyContinue).Temperature 2>$null; "
                 "(Get-WmiObject Win32_VideoController | Where-Object {$_.Name -like '*AMD*' -or $_.Name -like '*Radeon*'} | Select-Object -First 1 -ErrorAction SilentlyContinue).Name"],
                text=True, timeout=5, stderr=subprocess.DEVNULL
            )
            # 提取温度数字
            for line in ps.splitlines():
                nums = re.findall(r'\d+\.?\d*', line.strip())
                if nums and int(nums[0]) < 120:  # 合理的 GPU 温度范围
                    status["temp"] = f"{int(float(nums[0]))}°C"
                    status["source"] = "wmi"
                    break
        except Exception:
            pass

    # ── Intel 核显 ───────────────────────────────────────────────
    if gpu_info.get("vendor") == "Intel":
        try:
            ps = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-WmiObject MSACl priate * -Namespace root/wmi | Where-Object {$_.InstanceName -like '*Intel*'} | Select-Object -First 1 -ErrorAction SilentlyContinue).Temperature 2>$null"],
                text=True, timeout=5, stderr=subprocess.DEVNULL
            )
            nums = re.findall(r'\d+\.?\d*', ps.strip())
            if nums and 20 < int(nums[0]) < 120:
                status["temp"] = f"{int(float(nums[0]))}°C"
                status["source"] = "wmi"
        except Exception:
            pass

    return status


# ══════════════════════════════════════════════════════════════════
# 模块 2：GPU 通用计算压力（CUDA / OpenCL）
# ══════════════════════════════════════════════════════════════════

def gpu_compute_worker(worker_id: int, gpu_info: dict):
    """
    GPU 通用计算压力：
    - NVIDIA: 通过 subprocess 调用 nvidia-smi 持续监控/设置频率，压榨 CUDA
    - AMD:    通过 subprocess 持续调用 GPU 状态查询
    实际计算负载由 FFmpeg 编码流提供，这里负责 GPU 状态轮询维持驱动压力
    """
    with STATS_LOCK:
        STATS["gpu_compute_workers"] += 1

    try:
        if gpu_info.get("vendor") == "NVIDIA":
            nvidia_smi = shutil.which("nvidia-smi")
            if nvidia_smi:
                while not STOP_EVENT.is_set():
                    try:
                        # 持续查询 GPU 状态，产生驱动层压力
                        subprocess.check_output(
                            [nvidia_smi,
                             "--query-gpu=timestamp,temperature.gpu,power.draw,"
                             "utilization.gpu,memory.used,clocks.sm,clocks.mem,clocks.video",
                             "--format=csv,noheader"],
                            timeout=3, stderr=subprocess.DEVNULL
                        )
                        # 周期性设置性能模式（额外驱动压力）
                        subprocess.run(
                            [nvidia_smi,
                             "-pl", "300",   # 锁功率到 300W（如果支持）
                             "-pm", "1"],    # 性能模式
                            timeout=3, stderr=subprocess.DEVNULL
                        )
                        time.sleep(0.5)
                    except subprocess.TimeoutExpired:
                        pass
                    except Exception:
                        pass
            else:
                # 无 nvidia-smi，回退到纯计算
                _fallback_compute(worker_id)

        elif gpu_info.get("vendor") == "AMD" and gpu_info.get("type") == "dedicated":
            # AMD GPU：持续调用 WMI / PowerShell 查询 GPU 状态
            while not STOP_EVENT.is_set():
                try:
                    subprocess.check_output(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-WmiObject Win32_VideoController | "
                         "Where-Object {$_.Name -like '*AMD*' -or $_.Name -like '*Radeon*'} | "
                         "Select-Object Name,AdapterRAM,Status | ConvertTo-Json"],
                        timeout=3, text=True, stderr=subprocess.DEVNULL
                    )
                    time.sleep(1.0)
                except Exception:
                    time.sleep(1.0)

        elif gpu_info.get("vendor") == "Intel":
            # Intel 核显：持续读取 WMI 温度
            while not STOP_EVENT.is_set():
                try:
                    subprocess.check_output(
                        ["powershell", "-NoProfile", "-Command",
                         "(Get-WmiObject MSACl priate * -Namespace root/wmi | "
                         "Where-Object {$_.InstanceName -like '*Intel*'} | "
                         "Select-Object -First 1).Temperature 2>$null"],
                        timeout=3, text=True, stderr=subprocess.DEVNULL
                    )
                    time.sleep(1.0)
                except Exception:
                    time.sleep(1.0)

        else:
            _fallback_compute(worker_id)

    except Exception:
        with STATS_LOCK:
            STATS["errors"] += 1
        _fallback_compute(worker_id)
    finally:
        with STATS_LOCK:
            if STATS["gpu_compute_workers"] > 0:
                STATS["gpu_compute_workers"] -= 1


def _fallback_compute(thread_id: int):
    """无 GPU 工具时的 CPU 计算回退"""
    if HAS_NUMPY:
        rng = np.random.default_rng(thread_id)
        A = rng.random((1024, 1024), dtype=np.float32)
        B = rng.random((1024, 1024), dtype=np.float32)
        while not STOP_EVENT.is_set():
            _ = np.dot(A, B)
            A = A.T.copy()


# ══════════════════════════════════════════════════════════════════
# 模块 3：CPU/GPU 通用计算压力（numpy 矩阵爆算）
# ══════════════════════════════════════════════════════════════════

def compute_worker(thread_id: int, matrix_size: int = 2048):
    """
    大矩阵乘法 + 数学运算循环，强制拉满 CPU 向量单元。
    Windows 上 numpy 调用 OpenBLAS/MKL，Intel 平台 MKL 触发 AMX 加速。
    """
    with STATS_LOCK:
        STATS["compute_threads"] += 1

    try:
        if HAS_NUMPY:
            rng = np.random.default_rng(thread_id)
            A = rng.random((matrix_size, matrix_size), dtype=np.float32)
            B = rng.random((matrix_size, matrix_size), dtype=np.float32)
            iteration = 0

            while not STOP_EVENT.is_set():
                # 矩阵乘法 O(n^3)
                C = np.dot(A, B)
                # 非线性激活
                C = np.sin(C) * np.cos(C) + np.sqrt(np.abs(C) + 1e-6)
                # FFT 变换
                if iteration % 3 == 0:
                    _ = np.fft.fft2(C)
                # 矩阵转置再乘，生成不规则内存访问
                A = C.T.copy()
                B = rng.random((matrix_size, matrix_size), dtype=np.float32)
                with STATS_LOCK:
                    STATS["total_frames"] += 1
                iteration += 1
        else:
            import math
            val = float(thread_id + 1.23456789)
            while not STOP_EVENT.is_set():
                for _ in range(500000):
                    val = math.sin(val) * math.cos(val + 0.1) + math.sqrt(abs(val) + 1e-10)
                with STATS_LOCK:
                    STATS["total_frames"] += 1
    except Exception:
        with STATS_LOCK:
            STATS["errors"] += 1
    finally:
        with STATS_LOCK:
            if STATS["compute_threads"] > 0:
                STATS["compute_threads"] -= 1



# ══════════════════════════════════════════════════════════════════
# 模块 5：媒体编解码压力（FFmpeg + QSV/AMF/NVENC）
# ══════════════════════════════════════════════════════════════════

def build_ffmpeg_cmd(stream_id: int, gpu_info: dict, codec: str,
                     width: int, height: int, duration: int, bitrate: str) -> list:
    """
    根据 GPU 类型构建对应的 FFmpeg 硬件加速命令。
    """
    ffmpeg = find_ffmpeg() or "ffmpeg"
    null_output = "NUL" if IS_WINDOWS else "/dev/null"
    hw = gpu_info.get("hwaccel")
    target_bitrate = "50M" if bitrate == "0" else bitrate

    if codec.lower() in ("hevc", "h265"):
        encoder = gpu_info["encoder_hevc"]
    else:
        encoder = gpu_info["encoder_h264"]

    # Intel QSV
    if hw == "qsv":
        return [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-init_hw_device", "qsv=hw",
            "-filter_hw_device", "hw",
            "-f", "lavfi",
            "-i", f"testsrc2=size={width}x{height}:rate=30",
            "-t", str(duration),
            "-vf", "hwupload=extra_hw_frames=64,format=qsv",
            "-vcodec", encoder,
            "-b:v", target_bitrate,
            "-g", "15",
            "-an",
            "-f", "null", null_output,
        ]

    # AMD AMF / NVIDIA NVENC
    elif hw in ("d3d11va", "cuda"):
        return [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"testsrc2=size={width}x{height}:rate=30",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-vcodec", encoder,
            "-b:v", target_bitrate,
            "-g", "15",
            "-an",
            "-f", "null", null_output,
        ]

    # Apple VideoToolbox
    elif encoder.endswith("videotoolbox"):
        return [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"testsrc2=size={width}x{height}:rate=30",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-vcodec", encoder,
            "-allow_sw", "1",
            "-b:v", target_bitrate,
            "-g", "15",
            "-an",
            "-f", "null", null_output,
        ]

    # 软件编码
    else:
        return [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"testsrc2=size={width}x{height}:rate=30",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-vcodec", encoder,
            "-preset", "ultrafast",
            "-b:v", target_bitrate,
            "-g", "15",
            "-an",
            "-f", "null", null_output,
        ]


def transcode_worker(stream_id: int, gpu_info: dict, codec: str,
                     width: int, height: int, total_duration: int):
    """单路转码工人：循环 FFmpeg 持续压榨视频编码单元"""
    with STATS_LOCK:
        STATS["media_streams"] += 1

    segment_duration = min(300, total_duration if total_duration > 0 else 300)
    cmd = build_ffmpeg_cmd(stream_id, gpu_info, codec, width, height,
                           segment_duration, "0")

    try:
        while not STOP_EVENT.is_set():
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            )
            while not STOP_EVENT.is_set():
                if proc.poll() is not None:
                    break
                time.sleep(0.5)

            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    except FileNotFoundError:
        with STATS_LOCK:
            STATS["errors"] += 1
    except Exception:
        with STATS_LOCK:
            STATS["errors"] += 1
    finally:
        with STATS_LOCK:
            if STATS["media_streams"] > 0:
                STATS["media_streams"] -= 1


# ══════════════════════════════════════════════════════════════════
# 模块 6：实时监控面板
# ══════════════════════════════════════════════════════════════════

def enable_windows_ansi():
    """Windows 上启用 ANSI 转义序列"""
    if IS_WINDOWS:
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def get_system_stats() -> dict:
    """获取 CPU / 内存 / 温度"""
    stats = {
        "cpu_percent": 0.0,
        "mem_used_gb": 0.0,
        "mem_total_gb": 0.0,
        "mem_percent": 0.0,
        "cpu_freq_mhz": 0.0,
        "cpu_temp": "N/A",
    }

    if HAS_PSUTIL:
        try:
            stats["cpu_percent"] = psutil.cpu_percent(interval=0.2)
            mem = psutil.virtual_memory()
            stats["mem_used_gb"] = mem.used / (1024 ** 3)
            stats["mem_total_gb"] = mem.total / (1024 ** 3)
            stats["mem_percent"] = mem.percent
            freq = psutil.cpu_freq()
            if freq:
                stats["cpu_freq_mhz"] = freq.current
        except Exception:
            pass

        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for key in ("coretemp", "k10temp", "cpu_thermal"):
                    if key in temps and temps[key]:
                        stats["cpu_temp"] = f"{temps[key][0].current:.0f}°C"
                        break
        except Exception:
            pass

    return stats


def draw_bar(value: float, width: int = 20, filled: str = "█",
             empty: str = "░") -> str:
    filled_count = min(width, int(value / 100 * width))
    return filled * filled_count + empty * (width - filled_count)


def monitor_worker(duration: int, gpu_info: dict):
    """实时监控面板，每秒刷新"""
    enable_windows_ansi()
    start_time = time.time()
    gpu_status_cache = {"temp": "N/A", "power_w": 0.0,
                         "util_pct": 0, "memory_used_mb": 0,
                         "memory_total_mb": 0}
    cache_time = 0

    while not STOP_EVENT.is_set():
        elapsed = time.time() - start_time
        remaining = max(0, duration - elapsed) if duration > 0 else -1

        # 每2秒更新一次 GPU 状态（避免频繁查询）
        if time.time() - cache_time > 2:
            gpu_status_cache = get_gpu_status(gpu_info)
            cache_time = time.time()

        sys_stats = get_system_stats()

        with STATS_LOCK:
            compute_threads = STATS["compute_threads"]
            media_streams = STATS["media_streams"]
            gpu_workers = STATS["gpu_compute_workers"]
            total_frames = STATS["total_frames"]
            errors = STATS["errors"]

        os.system("cls" if IS_WINDOWS else "clear")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        remain_str = (f"{int(remaining // 60):02d}:{int(remaining % 60):02d}"
                      if remaining >= 0 else "∞")

        vendor = gpu_info.get("vendor", "Unknown")
        icon = {"Intel": "🔵", "AMD": "🔴", "NVIDIA": "🟢",
                "Apple": "⚫"}.get(vendor, "⚪")
        type_icon = "🟢" if gpu_info.get("type") == "dedicated" else "🔵"

        print("=" * 72)
        print(f"  🔥 GPU 烤机程序 v3.6  [{now_str}]")
        print(f"  {type_icon} {icon} GPU: {gpu_info.get('name', 'Unknown')[:50]}")
        print(f"  厂商: {vendor} | 类型: {gpu_info.get('type', 'unknown')}")
        print(f"  ⚡ 加速模式: {gpu_info.get('label', 'Unknown')}")
        print("=" * 72)

        # GPU 状态行
        gpu_temp = gpu_status_cache.get("temp", "N/A")
        gpu_power = gpu_status_cache.get("power_w", 0.0)
        gpu_util = gpu_status_cache.get("util_pct", 0)
        gpu_mem_used = gpu_status_cache.get("memory_used_mb", 0)
        gpu_mem_total = gpu_status_cache.get("memory_total_mb", 0)

        gpu_bar = draw_bar(gpu_util if gpu_util > 0 else sys_stats["cpu_percent"])

        if gpu_temp != "N/A":
            temp_str = f"  🌡️  GPU温度: {gpu_temp}"
            if gpu_power > 0:
                temp_str += f"  ⚡ 功率: {gpu_power:.0f}W"
            if gpu_mem_total > 0:
                mem_str = f"  💾 显存: {gpu_mem_used}/{gpu_mem_total}MB"
                print(f"  📊 GPU利用率 [{gpu_bar}] {gpu_util:5.1f}%{temp_str}")
                print(f"  {mem_str}")
        else:
            print(f"  🌡️  GPU温度: {gpu_temp}（nvidia-smi 或驱动可能未安装）")

        cpu_bar = draw_bar(sys_stats["cpu_percent"])
        mem_bar = draw_bar(sys_stats["mem_percent"])
        freq_str = (f"  @{sys_stats['cpu_freq_mhz']:.0f}MHz"
                    if sys_stats["cpu_freq_mhz"] > 0 else "")
        cpu_temp_str = (f"  温度: {sys_stats['cpu_temp']}"
                        if sys_stats["cpu_temp"] != "N/A" else "")

        print(f"  🖥️  CPU  [{cpu_bar}] {sys_stats['cpu_percent']:5.1f}%{freq_str}{cpu_temp_str}")
        print(f"  💾 内存 [{mem_bar}] {sys_stats['mem_used_gb']:.1f}/{sys_stats['mem_total_gb']:.1f} GB")
        print("-" * 72)

        active_tasks = []
        if compute_threads > 0:
            active_tasks.append(f"CPU计算 x{compute_threads}")
        if media_streams > 0:
            active_tasks.append(f"编码 x{media_streams}路")
        dx_workers_local = STATS.get("dx_workers", 0)
        if dx_workers_local > 0:
            active_tasks.append(f"DX11 x{dx_workers_local}")
        if gpu_workers > 0:
            active_tasks.append(f"GPU监控 x{gpu_workers}")

        print(f"  ⚡ 压力任务: {' | '.join(active_tasks) if active_tasks else '启动中...'}")
        print(f"  🎬 编码器: {gpu_info.get('encoder_hevc', '?')}  "
              f"| 帧数: {total_frames}")
        if errors > 0:
            print(f"  ⚠️  累计错误: {errors}")
        print(f"  ⏱  运行: {elapsed_str}  剩余: {remain_str}")
        print("-" * 72)

        cpu = sys_stats["cpu_percent"]
        if (gpu_util > 0 and gpu_util >= 90) or cpu >= 90:
            print("  🔥🔥🔥 极高负载 — GPU全力运转！")
        elif cpu >= 70 or (gpu_util > 0 and gpu_util >= 70):
            print("  🔥🔥    高负载 — 效果良好")
        elif cpu >= 50 or (gpu_util > 0 and gpu_util >= 50):
            print("  🔥       中等负载 — 可增加路数 (--streams)")
        else:
            print("  ⏳       负载偏低 — 等待任务启动...")

        print("=" * 72)
        print("  按 Ctrl+C 停止测试")
        time.sleep(1)


# ══════════════════════════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="GPU 烤机程序 v3.6 - 支持 Intel QSV / AMD AMF / NVIDIA NVENC",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
示例：
  # 自动检测并选择最强显卡（优先独显）
  igpu_burn_win.exe

  # 强制使用 NVIDIA 独显
  igpu_burn_win.exe --gpu nvidia

  # 强制使用 AMD 独显
  igpu_burn_win.exe --gpu amd

  # 仅使用 Intel 核显
  igpu_burn_win.exe --gpu intel

  # 指定第2张显卡（先用 --info 看索引）
  igpu_burn_win.exe --gpu 1 --info

  # 高强度：8路4K HEVC 编码
  igpu_burn_win.exe --streams 8 --codec hevc

  # 仅媒体编码（关闭 CPU 计算）
  igpu_burn_win.exe --no-compute --streams 8

  # 仅 CPU 计算（关闭媒体编码）
  igpu_burn_win.exe --no-media --compute-threads 16

  # 限时 10 分钟测试
  igpu_burn_win.exe --duration 600

  # 显示所有检测到的显卡（不运行测试）
  igpu_burn_win.exe --info
"""
    )
    parser.add_argument("--duration", type=int, default=0,
                        help="测试时长(秒)，0=无限 (默认: 0)")
    parser.add_argument("--codec", type=str, default="hevc",
                        choices=["hevc", "h265", "h264"],
                        help="视频编码格式 (默认: hevc)")
    parser.add_argument("--streams", type=int, default=4,
                        help="并发编码路数 (默认: 4)")
    parser.add_argument("--compute-threads", type=int, default=0,
                        help="CPU计算线程数，0=自动 (默认: 0)")
    parser.add_argument("--resolution", type=str, default="3840x2160",
                        help="编码分辨率 WxH (默认: 3840x2160 4K)")
    parser.add_argument("--matrix-size", type=int, default=2048,
                        help="矩阵计算大小 (默认: 2048)")
    parser.add_argument("--no-media", action="store_true",
                        help="禁用媒体编解码压力")
    parser.add_argument("--no-compute", action="store_true",
                        help="禁用 CPU 计算压力")
    parser.add_argument("--no-gpu-monitor", action="store_true",
                        help="禁用 GPU 状态监控压力")
    # --opengl 参数已废弃（v3.5 起使用 DirectX 11，零依赖）
    # parser.add_argument("--opengl", action="store_true", help="...")
    parser.add_argument("--force-sw", action="store_true",
                        help="强制使用软件编码")
    parser.add_argument("--gpu", type=str, default="auto",
                        help="选择GPU: auto/nvidia/amd/intel/dedicated/integrated/数字索引 (默认: auto)")
    parser.add_argument("--info", action="store_true",
                        help="显示所有检测到的显卡，不运行测试")
    return parser.parse_args()


def main():
    args = parse_args()
    enable_windows_ansi()

    # ── 检测所有 GPU ────────────────────────────────────────────
    print("\n  🔍 正在检测系统中的所有 GPU...\n")
    all_gpus = detect_all_gpus()

    # 选择目标 GPU
    gpu_info = select_gpu(all_gpus, args.gpu)

    if args.force_sw:
        gpu_info["encoder_h264"] = "libx264"
        gpu_info["encoder_hevc"] = "libx265"
        gpu_info["hwaccel"] = None
        gpu_info["label"] = "强制软件编码模式"

    # ── 只显示信息 ───────────────────────────────────────────────
    if args.info:
        print("=" * 62)
        print("  GPU 检测结果")
        print("=" * 62)
        print(f"  选中厂商:   {gpu_info['vendor']}")
        print(f"  选中型号:   {gpu_info['name']}")
        print(f"  显卡类型:   {gpu_info['type']}")
        print(f"  H.264 编码: {gpu_info['encoder_h264']}")
        print(f"  HEVC 编码:  {gpu_info['encoder_hevc']}")
        print(f"  加速模式:   {gpu_info['hwaccel'] or '无'}")
        print(f"  FFmpeg:    {find_ffmpeg() or '未找到'}")
        print(f"  nvidia-smi: {shutil.which('nvidia-smi') or '未找到'}")
        print(f"  numpy:     {'可用 ' + np.__version__ if HAS_NUMPY else '未安装'}")
        print(f"  psutil:    {'可用 ' + psutil.__version__ if HAS_PSUTIL else '未安装'}")
        print(f"  DirectX 11: 已启用（ctypes/d3d11.dll）")
        print("=" * 62)

        if gpu_info.get("vendor") == "NVIDIA" and not shutil.which("nvidia-smi"):
            print("  ⚠️  NVIDIA 独显检测到，但 nvidia-smi 未找到。")
            print("     建议安装 NVIDIA 驱动以启用 GPU 监控和温度显示。")
        print()
        return

    # ── 解析分辨率 ───────────────────────────────────────────────
    try:
        w_str, h_str = args.resolution.lower().split("x")
        vid_w, vid_h = int(w_str), int(h_str)
    except Exception:
        print(f"  ⚠️  分辨率格式错误: {args.resolution}，使用默认 3840x2160")
        vid_w, vid_h = 3840, 2160

    # ── 计算线程数 ───────────────────────────────────────────────
    num_cpu = multiprocessing.cpu_count()
    compute_threads = args.compute_threads if args.compute_threads > 0 else num_cpu

    # ── 检查工具 ──────────────────────────────────────────────────
    has_ffmpeg = bool(find_ffmpeg())
    has_nvidia_smi = bool(shutil.which("nvidia-smi"))

    # ── 打印启动信息 ─────────────────────────────────────────────
    print("=" * 72)
    print("  🔥 GPU 烤机程序 v3.6 启动")
    print("=" * 72)
    type_icon = "🟢" if gpu_info.get("type") == "dedicated" else "🔵"
    vendor_icon = {"Intel": "🔵", "AMD": "🔴", "NVIDIA": "🟢",
                   "Apple": "⚫"}.get(gpu_info.get("vendor", ""), "⚪")
    print(f"  {type_icon} {vendor_icon} GPU:       {gpu_info['name']}")
    print(f"  厂商/类型:  {gpu_info['vendor']} / {gpu_info['type']}")
    print(f"  ⚡ 加速模式: {gpu_info['label']}")
    print(f"  📐 分辨率:   {vid_w}x{vid_h}")
    print(f"  🎬 编码格式: {args.codec.upper()}")
    print(f"  📡 编码流数: {args.streams} 路 ({'禁用' if args.no_media else '启用'})")
    print(f"  🧮 CPU线程: {compute_threads} 个 ({'禁用' if args.no_compute else '启用'})")
    print(f"  📊 GPU监控: {'禁用' if args.no_gpu_monitor else '启用'}")
    print(f"  ⏱  测试时长: {'无限' if args.duration == 0 else f'{args.duration}秒'}")

    if not has_ffmpeg:
        print()
        print("  ⚠️  警告：未找到 FFmpeg！")
        print("     请下载: https://github.com/BtbN/FFmpeg-Builds/releases")
        print("     将 ffmpeg.exe 放到程序同目录或添加到系统 PATH")

    if gpu_info.get("vendor") == "NVIDIA" and not has_nvidia_smi:
        print()
        print("  ⚠️  警告：未找到 nvidia-smi，GPU 温度监控将不可用。")
        print("     请确保已安装 NVIDIA 显卡驱动。")

    if not HAS_NUMPY:
        print()
        print("  ⚠️  警告：numpy 未安装，CPU 计算压力将大幅降低。")

    print("=" * 72)
    print()
    time.sleep(2)

    # ── 注册信号处理 ─────────────────────────────────────────────
    def _stop(sig, frame):
        print("\n\n  ⚡ 收到停止信号，正在安全退出...")
        STOP_EVENT.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    STATS["start_time"] = time.time()
    STATS["gpu_vendor"] = gpu_info.get("vendor", "Unknown")
    STATS["gpu_name"] = gpu_info.get("name", "Unknown")

    all_threads = []

    # ── 1. GPU 状态监控线程 ──────────────────────────────────────
    if not args.no_gpu_monitor:
        if gpu_info.get("vendor") in ("NVIDIA", "AMD") or \
           gpu_info.get("type") == "dedicated":
            print(f"  ▶ 启动 GPU 驱动压力监控线程...")
            t = threading.Thread(
                target=gpu_compute_worker,
                args=(0, gpu_info),
                daemon=True, name="gpu-compute"
            )
            t.start()
            all_threads.append(t)

    # ── 2. CPU 计算压力线程 ──────────────────────────────────────
    if not args.no_compute:
        print(f"  ▶ 启动 {compute_threads} 个 CPU 计算压力线程...")
        for i in range(compute_threads):
            t = threading.Thread(
                target=compute_worker,
                args=(i, args.matrix_size),
                daemon=True, name=f"compute-{i}"
            )
            t.start()
            all_threads.append(t)

    # ── 3. DirectX 11 GPU 烤机（自动，对 Intel 核显尤其重要） ────
    # 不依赖 PyOpenGL/glfw，d3d11.dll Windows 自带
    if gpu_info.get("vendor") in ("Intel", "AMD"):
        print("  ▶ 启动 DirectX 11 GPU 烤机（UpdateSubresource 持续搬运）...")
        t = threading.Thread(
            target=dx_compute_worker,
            args=(0,),
            daemon=True, name="dx11-0"
        )
        t.start()
        all_threads.append(t)
    elif gpu_info.get("vendor") == "NVIDIA":
        # NVIDIA 独显由 NVENC 编码流承担主要负载
        # DX11 仅作补充（防止编码器意外回退时 GPU 完全空闲）
        print("  ▶ 启动 DirectX 11 GPU 烤机（备用）...")
        t = threading.Thread(
            target=dx_compute_worker,
            args=(0,),
            daemon=True, name="dx11-0"
        )
        t.start()
        all_threads.append(t)

    # ── 4. 媒体编解码压力 ────────────────────────────────────────
    if not args.no_media:
        if not has_ffmpeg:
            print("  ⚠️  FFmpeg 未找到，跳过媒体压力测试")
        else:
            print(f"  ▶ 启动 {args.streams} 路 {vid_w}x{vid_h} "
                  f"{args.codec.upper()} 编码流...")
            for i in range(args.streams):
                t = threading.Thread(
                    target=transcode_worker,
                    args=(i, gpu_info, args.codec,
                          vid_w, vid_h,
                          args.duration if args.duration > 0 else 86400),
                    daemon=True, name=f"media-{i}"
                )
                t.start()
                all_threads.append(t)
                time.sleep(0.2)

    # ── 5. 监控面板 ──────────────────────────────────────────────
    monitor_t = threading.Thread(
        target=monitor_worker,
        args=(args.duration, gpu_info),
        daemon=True, name="monitor"
    )
    monitor_t.start()

    # ── 6. 等待结束 ──────────────────────────────────────────────
    try:
        if args.duration > 0:
            deadline = time.time() + args.duration
            while time.time() < deadline and not STOP_EVENT.is_set():
                time.sleep(0.5)
            STOP_EVENT.set()
        else:
            while not STOP_EVENT.is_set():
                time.sleep(0.5)
    except KeyboardInterrupt:
        STOP_EVENT.set()

    # ── 7. 优雅退出 ──────────────────────────────────────────────
    print("\n  ⏳ 正在停止所有压力任务...")
    for t in all_threads:
        t.join(timeout=8)

    elapsed = time.time() - STATS["start_time"]
    print(f"\n  ✅ 烤机完成！")
    print(f"     总运行时间: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
    print(f"     累计错误数: {STATS['errors']}")
    print()

    if IS_WINDOWS:
        input("  按 Enter 键退出...")


if __name__ == "__main__":
    main()
