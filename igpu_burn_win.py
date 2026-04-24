#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║         iGPU 烤机程序 - Windows 版                           ║
║         支持 Intel 核显 (QSV) / AMD 核显 (AMF)               ║
║                                                              ║
║  压力来源：                                                   ║
║    1. GPU 通用计算 —— numpy 矩阵爆算 + OpenCL (可选)          ║
║    2. 媒体编解码  —— FFmpeg + QSV/AMF 多路并发硬件转码         ║
║    3. OpenGL 3D  —— GLSL 计算着色器持续渲染 (可选)             ║
║                                                              ║
║  用法：                                                       ║
║    igpu_burn_win.exe [选项]                                   ║
║    python igpu_burn_win.py [选项]                             ║
╚══════════════════════════════════════════════════════════════╝
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
import ctypes
from datetime import datetime

# ── 可选依赖 ──────────────────────────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import OpenGL.GL as GL
    import OpenGL.GLUT as GLUT
    HAS_OPENGL = True
except ImportError:
    HAS_OPENGL = False

# ── 全局状态 ──────────────────────────────────────────────────
STOP_EVENT = threading.Event()
STATS = {
    "compute_threads": 0,
    "media_streams": 0,
    "gl_workers": 0,
    "start_time": 0,
    "total_frames": 0,
    "errors": 0,
    "gpu_vendor": "Unknown",
    "gpu_name": "Unknown",
    "encoder_used": "Unknown",
}
STATS_LOCK = threading.Lock()

IS_WINDOWS = platform.system() == "Windows"


# ══════════════════════════════════════════════════════════════
# 模块 0：GPU 自动检测
# ══════════════════════════════════════════════════════════════

def detect_gpu() -> dict:
    """
    自动检测 GPU 信息，返回 {vendor, name, encoder_ffmpeg, encoder_label}
    支持 Intel / AMD / NVIDIA (核显/独显混合环境)
    """
    result = {
        "vendor": "Unknown",
        "name": "Unknown",
        "encoder_h264": "libx264",   # 软件回退
        "encoder_hevc": "libx265",   # 软件回退
        "hwaccel": None,
        "label": "软件编码（未检测到硬件加速）",
    }

    # ── Windows：用 WMIC 查询 GPU ───────────────────────────
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get",
                 "Name,AdapterCompatibility", "/format:csv"],
                text=True, timeout=10, stderr=subprocess.DEVNULL
            )
            lines = [l.strip() for l in out.splitlines() if l.strip() and "Node" not in l]
            for line in lines:
                parts = line.split(",")
                if len(parts) >= 3:
                    compat = parts[1].lower()
                    name = parts[2]
                    if "intel" in compat or "intel" in name.lower():
                        result["vendor"] = "Intel"
                        result["name"] = name
                        result["encoder_h264"] = "h264_qsv"
                        result["encoder_hevc"] = "hevc_qsv"
                        result["hwaccel"] = "qsv"
                        result["label"] = f"Intel QSV 硬件加速 ({name})"
                        break
                    elif "amd" in compat or "radeon" in name.lower() or "amd" in name.lower():
                        result["vendor"] = "AMD"
                        result["name"] = name
                        result["encoder_h264"] = "h264_amf"
                        result["encoder_hevc"] = "hevc_amf"
                        result["hwaccel"] = "d3d11va"
                        result["label"] = f"AMD AMF 硬件加速 ({name})"
                        break
                    elif "nvidia" in compat or "geforce" in name.lower() or "nvidia" in name.lower():
                        result["vendor"] = "NVIDIA"
                        result["name"] = name
                        result["encoder_h264"] = "h264_nvenc"
                        result["encoder_hevc"] = "hevc_nvenc"
                        result["hwaccel"] = "cuda"
                        result["label"] = f"NVIDIA NVENC 硬件加速 ({name})"
                        break
        except Exception:
            pass

    # ── macOS / Linux 备用检测 ──────────────────────────────
    if result["vendor"] == "Unknown":
        try:
            if platform.system() == "Darwin":
                out = subprocess.check_output(
                    ["system_profiler", "SPDisplaysDataType"],
                    text=True, timeout=10, stderr=subprocess.DEVNULL
                )
                if "Intel" in out:
                    result.update({"vendor": "Intel", "encoder_h264": "h264_videotoolbox",
                                   "encoder_hevc": "hevc_videotoolbox", "label": "Intel + VideoToolbox"})
                elif "AMD" in out or "Radeon" in out:
                    result.update({"vendor": "AMD", "encoder_h264": "h264_videotoolbox",
                                   "encoder_hevc": "hevc_videotoolbox", "label": "AMD + VideoToolbox"})
                elif "Apple" in out or "M1" in out or "M2" in out or "M3" in out or "M4" in out:
                    result.update({"vendor": "Apple", "encoder_h264": "h264_videotoolbox",
                                   "encoder_hevc": "hevc_videotoolbox", "label": "Apple Silicon + VideoToolbox"})
        except Exception:
            pass

    # ── 验证 FFmpeg 是否真的支持所选硬件编码器 ──────────────
    result = _verify_ffmpeg_encoder(result)

    return result


def _verify_ffmpeg_encoder(gpu_info: dict) -> dict:
    """
    验证 FFmpeg 实际是否支持检测到的硬件编码器，不支持则回退到软件编码
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        gpu_info["label"] += "（FFmpeg 未找到，将使用软件编码）"
        return gpu_info

    hevc_enc = gpu_info["encoder_hevc"]
    if hevc_enc in ("libx265", "libx264"):
        return gpu_info  # 软件编码无需验证

    try:
        # 用一帧测试编码器是否可用
        test_cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=black:size=320x240:rate=1",
            "-t", "0.1",
            "-pix_fmt", "yuv420p",
            "-vcodec", hevc_enc,
            "-f", "null", "NUL" if IS_WINDOWS else "/dev/null"
        ]
        if gpu_info.get("hwaccel") == "qsv":
            test_cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
                        "-init_hw_device", "qsv=hw",
                        "-filter_hw_device", "hw",
                        "-f", "lavfi", "-i", "color=black:size=320x240:rate=1",
                        "-t", "0.1",
                        "-vf", "hwupload=extra_hw_frames=64,format=qsv",
                        "-vcodec", hevc_enc,
                        "-f", "null", "NUL" if IS_WINDOWS else "/dev/null"]

        proc = subprocess.run(test_cmd, timeout=15,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        stderr_text = proc.stderr.decode(errors="ignore")
        
        if proc.returncode != 0 and ("not found" in stderr_text.lower() or
                                       "encoder" in stderr_text.lower() or
                                       "unknown" in stderr_text.lower()):
            # 硬件编码器不可用，回退软件编码
            print(f"  ⚠️  {hevc_enc} 不可用，回退到软件编码")
            gpu_info["encoder_h264"] = "libx264"
            gpu_info["encoder_hevc"] = "libx265"
            gpu_info["hwaccel"] = None
            gpu_info["label"] += "（硬件加速不可用，已回退软件编码）"
    except Exception:
        pass

    return gpu_info


# ══════════════════════════════════════════════════════════════
# 模块 1：CPU/GPU 通用计算压力（numpy 矩阵爆算）
# ══════════════════════════════════════════════════════════════

def compute_worker(thread_id: int, matrix_size: int = 2048):
    """
    大矩阵乘法 + 数学运算循环，强制拉满 CPU 向量单元 / GPU 计算单元。
    Windows 上 numpy 调用 OpenBLAS/MKL，Intel 平台上 MKL 会直接触发 AMX 加速。
    """
    with STATS_LOCK:
        STATS["compute_threads"] += 1

    try:
        if HAS_NUMPY:
            # 每线程分配独立的大矩阵，防止 CPU 缓存复用降低负载
            rng = np.random.default_rng(thread_id)
            A = rng.random((matrix_size, matrix_size), dtype=np.float32)
            B = rng.random((matrix_size, matrix_size), dtype=np.float32)
            iteration = 0

            while not STOP_EVENT.is_set():
                # 矩阵乘法 —— O(n^3) 极高计算密度
                C = np.dot(A, B)
                # 非线性激活，让执行单元做更多工作
                C = np.sin(C) * np.cos(C) + np.sqrt(np.abs(C) + 1e-6)
                # FFT 变换 —— 不同计算模式，覆盖更多执行单元
                if iteration % 3 == 0:
                    _ = np.fft.fft2(C)
                # 矩阵转置再乘，产生不规则内存访问
                A = C.T.copy()
                B = rng.random((matrix_size, matrix_size), dtype=np.float32)
                with STATS_LOCK:
                    STATS["total_frames"] += 1
                iteration += 1
        else:
            # 纯 Python 浮点循环（无 numpy 时的降级方案）
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
            STATS["compute_threads"] -= 1


# ══════════════════════════════════════════════════════════════
# 模块 2：OpenGL GLSL 着色器 3D 压力
# ══════════════════════════════════════════════════════════════

# GLSL 片元着色器：密集数学运算，专门压榨 GPU 着色器单元
FRAG_SHADER_SRC = """
#version 330 core
out vec4 FragColor;
uniform float u_time;
uniform vec2 u_resolution;

// 复杂数学运算：满载 GPU 着色器单元
vec3 heavy_calc(vec2 uv, float t) {
    vec3 col = vec3(0.0);
    // 200 次迭代，强制执行单元满负荷
    for (int i = 0; i < 200; i++) {
        float fi = float(i);
        vec2 p = uv * (fi * 0.01 + 1.0);
        col += vec3(
            sin(p.x * 7.3 + t * 1.1 + fi * 0.05),
            cos(p.y * 5.7 + t * 0.9 + fi * 0.07),
            sin((p.x + p.y) * 3.1 + t * 1.3 + fi * 0.03)
        );
        // transcendental 函数堆叠
        col = normalize(col) * (sin(t * 0.3 + fi) * 0.5 + 0.5) + 0.001;
    }
    return col;
}

void main() {
    vec2 uv = (gl_FragCoord.xy - u_resolution * 0.5) / u_resolution.y;
    vec3 color = heavy_calc(uv, u_time);
    FragColor = vec4(color, 1.0);
}
"""

VERT_SHADER_SRC = """
#version 330 core
layout (location = 0) in vec2 aPos;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

def opengl_worker(worker_id: int, width: int = 1920, height: int = 1080):
    """
    用 OpenGL + GLSL 着色器持续渲染高计算密度帧，压榨 GPU 3D 单元。
    需要 PyOpenGL + GLFW。
    """
    if not HAS_OPENGL:
        # OpenGL 不可用，退回到 numpy 计算
        compute_worker(worker_id + 100, matrix_size=1536)
        return

    try:
        import glfw
        if not glfw.init():
            compute_worker(worker_id + 100, matrix_size=1536)
            return

        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)  # 隐藏窗口
        window = glfw.create_window(width, height, f"IGPUBurn-{worker_id}", None, None)
        if not window:
            glfw.terminate()
            compute_worker(worker_id + 100, matrix_size=1536)
            return

        glfw.make_context_current(window)

        # 编译着色器
        def _compile(src, shader_type):
            s = GL.glCreateShader(shader_type)
            GL.glShaderSource(s, src)
            GL.glCompileShader(s)
            if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(s).decode())
            return s

        vert = _compile(VERT_SHADER_SRC, GL.GL_VERTEX_SHADER)
        frag = _compile(FRAG_SHADER_SRC, GL.GL_FRAGMENT_SHADER)
        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, vert)
        GL.glAttachShader(prog, frag)
        GL.glLinkProgram(prog)
        GL.glUseProgram(prog)

        # 全屏四边形 VAO
        quad = np.array([-1,-1, 1,-1, 1,1, -1,-1, 1,1, -1,1], dtype=np.float32)
        vao = GL.glGenVertexArrays(1)
        vbo = GL.glGenBuffers(1)
        GL.glBindVertexArray(vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STATIC_DRAW)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 8, None)
        GL.glEnableVertexAttribArray(0)

        loc_time = GL.glGetUniformLocation(prog, "u_time")
        loc_res  = GL.glGetUniformLocation(prog, "u_resolution")
        GL.glUniform2f(loc_res, float(width), float(height))

        with STATS_LOCK:
            STATS["gl_workers"] += 1

        t0 = time.time()
        while not STOP_EVENT.is_set() and not glfw.window_should_close(window):
            GL.glUniform1f(loc_time, time.time() - t0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            GL.glBindVertexArray(vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
            glfw.swap_buffers(window)
            glfw.poll_events()
            with STATS_LOCK:
                STATS["total_frames"] += 1

        glfw.terminate()
    except Exception:
        with STATS_LOCK:
            STATS["errors"] += 1
        compute_worker(worker_id + 100, matrix_size=1536)
    finally:
        with STATS_LOCK:
            if STATS["gl_workers"] > 0:
                STATS["gl_workers"] -= 1


# ══════════════════════════════════════════════════════════════
# 模块 3：媒体编解码压力（FFmpeg + QSV/AMF/NVENC 多路并发）
# ══════════════════════════════════════════════════════════════

def build_ffmpeg_cmd(stream_id: int, gpu_info: dict, codec: str,
                     width: int, height: int, duration: int, bitrate: str) -> list:
    """
    根据 GPU 类型构建对应的 FFmpeg 硬件加速命令。
    - Intel QSV：通过 init_hw_device qsv 初始化，上传帧到 QSV 内存
    - AMD AMF：直接指定 h264_amf / hevc_amf 编码器
    - NVIDIA NVENC：直接指定 h264_nvenc / hevc_nvenc
    - 软件回退：libx264 / libx265（无硬件加速）
    """
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    null_output = "NUL" if IS_WINDOWS else "/dev/null"
    hw = gpu_info.get("hwaccel")
    target_bitrate = "50M" if bitrate == "0" else bitrate

    # 选择编码器
    if codec.lower() in ("hevc", "h265"):
        encoder = gpu_info["encoder_hevc"]
    else:
        encoder = gpu_info["encoder_h264"]

    # ── Intel QSV 专用命令 ─────────────────────────────────
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

    # ── AMD AMF / NVIDIA NVENC ─────────────────────────────
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

    # ── Apple VideoToolbox ─────────────────────────────────
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

    # ── 软件编码（回退） ────────────────────────────────────
    else:
        preset = "ultrafast"  # 软件编码用 ultrafast 最大化 CPU 负载
        return [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"testsrc2=size={width}x{height}:rate=30",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-vcodec", encoder,
            "-preset", preset,
            "-b:v", target_bitrate,
            "-g", "15",
            "-an",
            "-f", "null", null_output,
        ]


def transcode_worker(stream_id: int, gpu_info: dict, codec: str,
                     width: int, height: int, total_duration: int):
    """
    单路转码工人：循环运行 FFmpeg，持续压榨视频编码单元。
    """
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
            STATS["media_streams"] -= 1


# ══════════════════════════════════════════════════════════════
# 模块 4：实时监控面板（Windows 彩色终端）
# ══════════════════════════════════════════════════════════════

def enable_windows_ansi():
    """在 Windows 上启用 ANSI 转义序列支持"""
    if IS_WINDOWS:
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def get_system_stats() -> dict:
    """获取系统资源使用情况"""
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


def draw_bar(value: float, width: int = 20, filled: str = "█", empty: str = "░") -> str:
    """绘制进度条"""
    filled_count = min(width, int(value / 100 * width))
    return filled * filled_count + empty * (width - filled_count)


def monitor_worker(duration: int, gpu_info: dict):
    """实时监控面板，每秒刷新"""
    enable_windows_ansi()
    start_time = time.time()

    while not STOP_EVENT.is_set():
        elapsed = time.time() - start_time
        remaining = max(0, duration - elapsed) if duration > 0 else -1

        sys_stats = get_system_stats()

        with STATS_LOCK:
            compute_threads = STATS["compute_threads"]
            media_streams   = STATS["media_streams"]
            gl_workers      = STATS["gl_workers"]
            total_frames    = STATS["total_frames"]
            errors          = STATS["errors"]

        # 清屏
        os.system("cls" if IS_WINDOWS else "clear")

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        remain_str  = (f"{int(remaining // 60):02d}:{int(remaining % 60):02d}"
                       if remaining >= 0 else "∞")

        vendor = gpu_info.get("vendor", "Unknown")
        if vendor == "Intel":
            gpu_icon = "🔵"
        elif vendor == "AMD":
            gpu_icon = "🔴"
        elif vendor == "NVIDIA":
            gpu_icon = "🟢"
        elif vendor == "Apple":
            gpu_icon = "⚫"
        else:
            gpu_icon = "⚪"

        print("=" * 72)
        print(f"  🔥 iGPU 烤机程序 v2.0 - Windows 版  [{now_str}]")
        print(f"  {gpu_icon} GPU: {gpu_info.get('name', 'Unknown')[:50]}")
        print(f"  ⚡ 加速模式: {gpu_info.get('label', 'Unknown')}")
        print("=" * 72)

        cpu_bar = draw_bar(sys_stats["cpu_percent"])
        mem_bar = draw_bar(sys_stats["mem_percent"])
        freq_str = (f"  @{sys_stats['cpu_freq_mhz']:.0f}MHz"
                    if sys_stats["cpu_freq_mhz"] > 0 else "")
        temp_str = (f"  温度: {sys_stats['cpu_temp']}"
                    if sys_stats["cpu_temp"] != "N/A" else "")

        print(f"  🖥️  CPU  [{cpu_bar}] {sys_stats['cpu_percent']:5.1f}%{freq_str}{temp_str}")
        print(f"  💾 内存 [{mem_bar}] {sys_stats['mem_used_gb']:.1f}/{sys_stats['mem_total_gb']:.1f} GB ({sys_stats['mem_percent']:.1f}%)")
        print("-" * 72)

        active_tasks = []
        if compute_threads > 0:
            active_tasks.append(f"计算 x{compute_threads}")
        if media_streams > 0:
            active_tasks.append(f"编码 x{media_streams} 路")
        if gl_workers > 0:
            active_tasks.append(f"OpenGL x{gl_workers}")

        print(f"  ⚡ 压力任务: {' | '.join(active_tasks) if active_tasks else '启动中...'}")
        print(f"  🎬 媒体编码: {media_streams} 路活跃  ({gpu_info.get('encoder_hevc', '?')})")
        print(f"  🧮 计算线程: {compute_threads} 个活跃")
        if errors > 0:
            print(f"  ⚠️  累计错误: {errors}")
        print(f"  ⏱  运行时间: {elapsed_str}  剩余: {remain_str}")
        print("-" * 72)

        # 负载评估
        cpu = sys_stats["cpu_percent"]
        if cpu >= 90:
            print("  🔥🔥🔥 极高负载 — 核显全力运转！")
        elif cpu >= 70:
            print("  🔥🔥    高负载 — 效果良好")
        elif cpu >= 50:
            print("  🔥       中等负载 — 可增加路数 (--streams)")
        else:
            print("  ⏳       负载偏低 — 等待任务启动...")

        print("=" * 72)
        print("  按 Ctrl+C 停止测试")

        time.sleep(1)


# ══════════════════════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="iGPU 烤机程序 v2.0 - 支持 Intel QSV / AMD AMF / 软件回退",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
示例：
  # 默认模式：自动检测 GPU，4路4K HEVC + 全核计算
  igpu_burn_win.exe

  # 高强度：8路4K HEVC
  igpu_burn_win.exe --streams 8 --codec hevc

  # H.264（负载略低但更兼容）
  igpu_burn_win.exe --streams 6 --codec h264

  # 仅测媒体编解码（关闭计算压力）
  igpu_burn_win.exe --no-compute --streams 8

  # 仅测计算（关闭媒体编码）
  igpu_burn_win.exe --no-media --compute-threads 16

  # 限时测试（300秒）
  igpu_burn_win.exe --duration 300

  # 启用 OpenGL 3D 着色器（需要安装 PyOpenGL + GLFW）
  igpu_burn_win.exe --opengl
"""
    )
    parser.add_argument("--duration",        type=int,   default=0,
                        help="测试时长(秒)，0=无限 (默认: 0)")
    parser.add_argument("--codec",           type=str,   default="hevc",
                        choices=["hevc", "h265", "h264"],
                        help="视频编码格式 (默认: hevc)")
    parser.add_argument("--streams",         type=int,   default=4,
                        help="并发编码路数，越多压力越大 (默认: 4)")
    parser.add_argument("--compute-threads", type=int,   default=0,
                        help="计算线程数，0=自动(CPU核心数) (默认: 0)")
    parser.add_argument("--resolution",      type=str,   default="3840x2160",
                        help="编码分辨率 WxH (默认: 3840x2160 4K)")
    parser.add_argument("--matrix-size",     type=int,   default=2048,
                        help="矩阵计算大小 (默认: 2048)")
    parser.add_argument("--no-media",        action="store_true",
                        help="禁用媒体编解码压力")
    parser.add_argument("--no-compute",      action="store_true",
                        help="禁用计算压力")
    parser.add_argument("--opengl",          action="store_true",
                        help="启用 OpenGL GLSL 着色器压力（需 PyOpenGL+GLFW）")
    parser.add_argument("--force-sw",        action="store_true",
                        help="强制使用软件编码（忽略硬件加速）")
    parser.add_argument("--info",            action="store_true",
                        help="只显示 GPU 信息，不运行压力测试")
    return parser.parse_args()


def main():
    args = parse_args()
    enable_windows_ansi()

    # ── 检测 GPU ────────────────────────────────────────────
    print("\n  🔍 正在检测 GPU 和硬件加速支持...\n")
    gpu_info = detect_gpu()

    if args.force_sw:
        gpu_info["encoder_h264"] = "libx264"
        gpu_info["encoder_hevc"] = "libx265"
        gpu_info["hwaccel"] = None
        gpu_info["label"] = "强制软件编码模式"

    # ── 只显示信息 ──────────────────────────────────────────
    if args.info:
        print("=" * 60)
        print("  GPU 检测结果")
        print("=" * 60)
        print(f"  厂商:       {gpu_info['vendor']}")
        print(f"  型号:       {gpu_info['name']}")
        print(f"  H.264 编码: {gpu_info['encoder_h264']}")
        print(f"  HEVC 编码:  {gpu_info['encoder_hevc']}")
        print(f"  加速模式:   {gpu_info['label']}")
        print(f"  FFmpeg:     {shutil.which('ffmpeg') or '未找到'}")
        print(f"  numpy:      {'可用 ' + np.__version__ if HAS_NUMPY else '未安装'}")
        print(f"  psutil:     {'可用 ' + psutil.__version__ if HAS_PSUTIL else '未安装'}")
        print(f"  PyOpenGL:   {'可用' if HAS_OPENGL else '未安装'}")
        print("=" * 60)
        return

    # ── 解析分辨率 ──────────────────────────────────────────
    try:
        w_str, h_str = args.resolution.lower().split("x")
        vid_w, vid_h = int(w_str), int(h_str)
    except Exception:
        print(f"  ⚠️  分辨率格式错误: {args.resolution}，使用默认 3840x2160")
        vid_w, vid_h = 3840, 2160

    # ── 计算线程数 ──────────────────────────────────────────
    num_cpu = multiprocessing.cpu_count()
    compute_threads = args.compute_threads if args.compute_threads > 0 else num_cpu

    # ── 检查 FFmpeg ─────────────────────────────────────────
    has_ffmpeg = bool(shutil.which("ffmpeg"))

    # ── 打印启动信息 ────────────────────────────────────────
    print("=" * 72)
    print("  🔥 iGPU 烤机程序 v2.0 启动")
    print("=" * 72)
    vendor = gpu_info.get("vendor", "Unknown")
    icon = {"Intel": "🔵", "AMD": "🔴", "NVIDIA": "🟢", "Apple": "⚫"}.get(vendor, "⚪")
    print(f"  {icon} GPU:        {gpu_info['name']}")
    print(f"  ⚡ 加速模式:  {gpu_info['label']}")
    print(f"  📐 分辨率:    {vid_w}x{vid_h}")
    print(f"  🎬 编码格式:  {args.codec.upper()}")
    print(f"  📡 编码流数:  {args.streams} 路 ({'禁用' if args.no_media else '启用'})")
    print(f"  🧮 计算线程: {compute_threads} 个 ({'禁用' if args.no_compute else '启用'})")
    print(f"  ⏱  测试时长:  {'无限' if args.duration == 0 else f'{args.duration}秒'}")
    print(f"  🖥️  OpenGL:    {'启用' if args.opengl else '禁用'}")
    if not has_ffmpeg:
        print()
        print("  ⚠️  警告：未找到 FFmpeg！")
        print("       媒体编解码压力将无法启动。")
        print("       请下载并安装 FFmpeg：https://ffmpeg.org/download.html")
        print("       下载后将 ffmpeg.exe 放到程序同目录或添加到系统 PATH")
    if not HAS_NUMPY:
        print()
        print("  ⚠️  警告：numpy 未安装，计算压力将大幅降低")
    print("=" * 72)
    print()
    time.sleep(2)

    # ── 注册信号处理 ────────────────────────────────────────
    def _stop(sig, frame):
        print("\n\n  ⚡ 收到停止信号，正在安全退出...")
        STOP_EVENT.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    STATS["start_time"] = time.time()
    STATS["gpu_vendor"] = gpu_info.get("vendor", "Unknown")
    STATS["gpu_name"]   = gpu_info.get("name", "Unknown")

    all_threads = []

    # ── 1. 计算压力线程 ─────────────────────────────────────
    if not args.no_compute:
        print(f"  ▶ 启动 {compute_threads} 个计算压力线程...")
        for i in range(compute_threads):
            t = threading.Thread(
                target=compute_worker,
                args=(i, args.matrix_size),
                daemon=True,
                name=f"compute-{i}"
            )
            t.start()
            all_threads.append(t)

    # ── 2. OpenGL 压力（可选） ──────────────────────────────
    if args.opengl:
        if HAS_OPENGL:
            print("  ▶ 启动 OpenGL GLSL 3D 压力...")
            t = threading.Thread(
                target=opengl_worker,
                args=(0, 1920, 1080),
                daemon=True,
                name="opengl-0"
            )
            t.start()
            all_threads.append(t)
        else:
            print("  ⚠️  OpenGL 未安装，跳过 3D 压力（pip install PyOpenGL PyOpenGL-accelerate glfw）")

    # ── 3. 媒体编解码压力 ────────────────────────────────────
    if not args.no_media:
        if not has_ffmpeg:
            print("  ⚠️  FFmpeg 未找到，跳过媒体压力测试")
        else:
            print(f"  ▶ 启动 {args.streams} 路 {vid_w}x{vid_h} {args.codec.upper()} 编码流...")
            for i in range(args.streams):
                t = threading.Thread(
                    target=transcode_worker,
                    args=(i, gpu_info, args.codec,
                          vid_w, vid_h,
                          args.duration if args.duration > 0 else 86400),
                    daemon=True,
                    name=f"media-{i}"
                )
                t.start()
                all_threads.append(t)
                time.sleep(0.2)

    # ── 4. 监控面板 ─────────────────────────────────────────
    monitor_t = threading.Thread(
        target=monitor_worker,
        args=(args.duration, gpu_info),
        daemon=True,
        name="monitor"
    )
    monitor_t.start()

    # ── 5. 等待结束 ─────────────────────────────────────────
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

    # ── 6. 优雅退出 ─────────────────────────────────────────
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
