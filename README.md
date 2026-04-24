# GPU 烤机程序 - Windows 版

支持 **Intel 核显 (QSV)** / **AMD 核显 (AMF)** / **AMD 独显 (AMF)** / **NVIDIA 独显 (NVENC)**

自动检测系统所有显卡，优先选择独立显卡。

## 下载 EXE

👉 **[点击下载 igpu_burn_win.exe](https://github.com/XYXS-ZHXD/igpu-burn-win/releases/download/v1.0/igpu_burn_win.exe)**

> 程序约 25MB，双击即可运行（无需安装）

## 使用前准备

程序运行需要 **ffmpeg.exe**，请下载：
1. 访问 https://github.com/BtbN/FFmpeg-Builds/releases
2. 下载 `ffmpeg-master-latest-win64-gpl.zip`
3. 解压后把 `fffmpeg.exe` 放到 `igpu_burn_win.exe` **同目录**
4. 双击运行

## 快速使用

```bash
# 默认模式（自动选择最强显卡，优先独显）
igpu_burn_win.exe

# 强制使用 NVIDIA 独显
igpu_burn_win.exe --gpu nvidia

# 强制使用 AMD 独显
igpu_burn_win.exe --gpu amd

# 仅使用 Intel 核显
igpu_burn_win.exe --gpu intel

# 高强度：8路 4K HEVC 编码
igpu_burn_win.exe --streams 8 --codec hevc

# 显示所有检测到的显卡（不运行测试）
igpu_burn_win.exe --info

# 指定第 N 张显卡
igpu_burn_win.exe --gpu 1

# 限时 10 分钟测试
igpu_burn_win.exe --duration 600

# 启用 OpenGL 3D 压力（需 pip install PyOpenGL glfw）
igpu_burn_win.exe --opengl

# 仅 CPU 计算（关闭媒体编码）
igpu_burn_win.exe --no-media --compute-threads 16

# 仅媒体编码（关闭 CPU 计算）
igpu_burn_win.exe --no-compute --streams 8
```

## 支持的显卡与加速

| 显卡类型 | 厂商 | 编码器 | 监控 |
|---------|------|--------|------|
| 独立显卡 | NVIDIA | NVENC (h264_nvenc/hevc_nvenc) | nvidia-smi |
| 独立显卡 | AMD | AMF (h264_amf/hevc_amf) | WMI |
| 集成显卡 | Intel | QSV (h264_qsv/hevc_qsv) | WMI |
| 集成显卡 | AMD | AMF (h264_amf/hevc_amf) | WMI |
| 集成显卡 | Apple Silicon | VideoToolbox | - |
| 无硬件加速 | - | 软件编码 (libx264/libx265) | - |

## GPU 选择策略

`--gpu auto`（默认）自动按以下优先级选择：
1. **独显优先**：NVIDIA > AMD（自动检测RX/RTX/RADEON等关键词）
2. **无独显则选核显**：Intel > AMD > Apple Silicon

## 压力来源

1. **GPU 硬件编码**：FFmpeg 多路并发 4K HEVC/H.264 编码
2. **GPU 驱动压力**：`nvidia-smi` 持续查询（NVIDIA独显专享）
3. **CPU 计算**：numpy 矩阵乘法 + FFT 持续拉满 CPU
4. **OpenGL 3D**（可选）：GLSL 着色器持续渲染

## 监控面板

- GPU 温度（NVIDIA: nvidia-smi, AMD/Intel: WMI）
- GPU 功率（NVIDIA 独显）
- GPU 利用率
- GPU 显存使用量
- CPU 利用率 + 温度
- 内存使用量

## 依赖

| 依赖 | 用途 | 必需 |
|------|------|------|
| ffmpeg.exe | 硬件编码 | ✅ 必需 |
| numpy | CPU 计算加速 | 推荐 |
| psutil | 系统监控 | 推荐 |
| PyOpenGL + glfw | OpenGL 3D 压力 | 可选 |
| nvidia-smi | NVIDIA GPU 监控 | NVIDIA 用户推荐 |

## 编译 EXE（开发者）

```bash
# Windows 上
pip install pyinstaller numpy psutil
pyinstaller --onefile --console --name igpu_burn_win --hidden-import numpy --hidden-import psutil --collect-all numpy igpu_burn_win.py
```

或在 GitHub Actions 自动构建：推送代码后自动生成 EXE。
