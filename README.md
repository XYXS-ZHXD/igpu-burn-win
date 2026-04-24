# GPU 烤机程序 - Windows 版

支持 **Intel 核显** / **AMD 核显+独显** / **NVIDIA 独显**

自动检测系统所有显卡，优先选择独立显卡。

## 下载 EXE

👉 **[点击下载 igpu_burn_win.exe](https://github.com/XYXS-ZHXD/igpu-burn-win/releases/download/v1.0/igpu_burn_win.exe)**

> 程序约 25MB，双击即可运行（无需安装）

## 压力来源

| 来源 | 适用显卡 | 说明 |
|------|---------|------|
| **OpenGL GLSL 着色器** | 全部 | 主力压力，渲染循环持续烤 GPU 执行单元 |
| FFmpeg 硬件编码 | NVIDIA/AMD 独显 | NVENC/AMF 硬件加速转码 |
| FFmpeg 软件编码 | 全部 | libx265 CPU编码，自动降级 |
| NumPy 矩阵计算 | 全部 | CPU 向量单元压力 |

> 💡 **OpenGL 3D 压力现已默认启用**，无需额外安装任何库！
> 程序内置重型 GLSL 计算着色器（200次迭代/像素），直接渲染 GPU 执行单元。

## 使用前准备

**FFmpeg（可选，用于媒体编码）**
1. 访问 https://github.com/BtbN/FFmpeg-Builds/releases
2. 下载 `ffmpeg-master-latest-win64-gpl.zip`
3. 解压后把 `ffmpeg.exe` 放到 `igpu_burn_win.exe` **同目录**
4. 程序启动时会提示「✅ 找到同目录 ffmpeg.exe」

> ⚠️ **Intel QSV 特别说明**：Intel QSV 编码需要用 Intel Media SDK 专门编译的 FFmpeg，
> 标准 BtbN 构建不包含 QSV。Intel 核显会自动使用 OpenGL 3D 方式烤机，无需额外操作。

## 快速使用

```bash
# 默认模式（自动选择最强显卡，OpenGL 3D 压力默认开启）
igpu_burn_win.exe

# 查看检测到的所有显卡
igpu_burn_win.exe --info

# 强制使用 NVIDIA 独显
igpu_burn_win.exe --gpu nvidia

# 强制使用 AMD 独显
igpu_burn_win.exe --gpu amd

# 仅使用 Intel 核显
igpu_burn_win.exe --gpu intel

# 高强度：8路 4K HEVC 编码（需有 ffmpeg.exe）
igpu_burn_win.exe --streams 8 --codec hevc

# 指定第 N 张显卡（先用 --info 看索引）
igpu_burn_win.exe --gpu 1

# 限时 10 分钟测试
igpu_burn_win.exe --duration 600

# 关闭 OpenGL（仅媒体编码+CPU计算）
igpu_burn_win.exe --no-opengl

# 仅 CPU 计算（关闭媒体编码和 OpenGL）
igpu_burn_win.exe --no-media --compute-threads 16
```

## 支持的显卡与加速

| 显卡 | 厂商 | 主要压力方式 | 编码加速 |
|------|------|------------|---------|
| 独显 | NVIDIA | OpenGL + NVENC | ✅ nvidia-smi 监控 |
| 独显 | AMD | OpenGL + AMF | ✅ 温度监控 |
| 核显 | Intel | **OpenGL 3D（主力）** | 软件编码 |
| 核显 | AMD | OpenGL + AMF | ✅ |
| 核显 | Apple Silicon | OpenGL + VideoToolbox | ✅ |

## 监控面板

- GPU 温度（NVIDIA: nvidia-smi，AMD: WMI）
- GPU 功率（NVIDIA 独显）
- GPU 利用率
- GPU 显存使用量
- CPU 利用率 + 温度 + 频率
- 内存使用量

## 编译 EXE（开发者）

```bash
# Windows 上（需要 Python 3.9+）
pip install pyinstaller numpy psutil PyOpenGL PyOpenGL-accelerate glfw
pyinstaller --onefile --console --name igpu_burn_win \
  --hidden-import numpy --hidden-import psutil \
  --hidden-import OpenGL --hidden-import glfw \
  --collect-all numpy --collect-all PyOpenGL --collect-all glfw \
  igpu_burn_win.py
```

推送代码后 GitHub Actions 自动构建 EXE。
