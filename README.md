# iGPU 烤机程序 v2.0 使用说明

## 📋 简介

iGPU 烤机程序 v2.0 是一款专为集成显卡（核显）设计的满载压力测试工具，同时压榨：

- **3D/计算单元**：numpy 大矩阵运算（可选 OpenGL GLSL 着色器）
- **视频编解码单元**：FFmpeg 多路硬件加速编码

## 🖥️ 支持的显卡

| 显卡品牌 | 硬件加速 | 说明 |
|---------|---------|------|
| Intel 核显 | **QSV（Quick Sync Video）** | 适用 Intel HD/UHD/Iris/Arc |
| AMD 核显 | **AMF（Advanced Media Framework）** | 适用 Radeon RX Vega/680M/760M 等 |
| NVIDIA 独显 | **NVENC** | 也支持，会自动检测 |
| 无硬件加速 | libx264/libx265 软件编码 | 自动回退 |

## 📦 安装方法

### 方法一：直接使用 EXE（推荐）

1. 下载 `igpu_burn_win.exe`
2. 下载 FFmpeg：https://github.com/BtbN/FFmpeg-Builds/releases
   - 选 `ffmpeg-master-latest-win64-gpl.zip`
   - 解压后将 `ffmpeg.exe` 放到 `igpu_burn_win.exe` 同目录
3. 双击运行或在命令提示符中执行

### 方法二：Python 源码运行

```bash
# 1. 安装 Python 3.9+（https://python.org）

# 2. 安装依赖
pip install numpy psutil

# 3. 运行
python igpu_burn_win.py
```

### 方法三：自己打包 EXE

1. 安装 Python 3.9+
2. 双击 `build_exe.bat`
3. 等待打包完成，输出在 `dist\igpu_burn_win.exe`

## 🚀 使用方法

### 基本用法

```
igpu_burn_win.exe [选项]
```

### 常用命令

```bash
# 查看 GPU 检测信息（不运行压力测试）
igpu_burn_win.exe --info

# 默认模式（4路4K HEVC + 全核计算）
igpu_burn_win.exe

# 高强度模式：8路4K HEVC（最大化媒体引擎负载）
igpu_burn_win.exe --streams 8 --codec hevc

# H.264 编码（相比 HEVC 负载略低但更兼容）
igpu_burn_win.exe --streams 6 --codec h264

# 限时测试（300秒后自动停止）
igpu_burn_win.exe --duration 300

# 仅测媒体编解码（关闭计算）
igpu_burn_win.exe --no-compute --streams 8

# 仅测计算（关闭媒体）
igpu_burn_win.exe --no-media --compute-threads 16

# 强制软件编码（不使用硬件加速，会拉满 CPU）
igpu_burn_win.exe --force-sw

# 启用 OpenGL 3D 着色器压力
igpu_burn_win.exe --opengl
```

### 完整参数说明

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `--duration` | 0 | 测试时长(秒)，0=无限 |
| `--codec` | hevc | 编码格式：hevc / h264 |
| `--streams` | 4 | 并发编码路数 |
| `--compute-threads` | 0 | 计算线程数（0=自动=CPU核心数）|
| `--resolution` | 3840x2160 | 编码分辨率 |
| `--matrix-size` | 2048 | 矩阵计算大小 |
| `--no-media` | - | 禁用媒体编解码压力 |
| `--no-compute` | - | 禁用计算压力 |
| `--opengl` | - | 启用 OpenGL GLSL 着色器 |
| `--force-sw` | - | 强制软件编码 |
| `--info` | - | 只显示 GPU 信息 |

## 📊 监控面板说明

运行后会显示实时监控面板：

```
========================================================================
  🔥 iGPU 烤机程序 v2.0 - Windows 版  [2026-04-24 10:30:00]
  🔵 GPU: Intel(R) Iris(R) Xe Graphics
  ⚡ 加速模式: Intel QSV 硬件加速
========================================================================
  🖥️  CPU  [████████████████████] 100.0%  @4200MHz  温度: 85°C
  💾 内存  [████░░░░░░░░░░░░░░░░]  8.2/16.0 GB (51.3%)
------------------------------------------------------------------------
  ⚡ 压力任务: 计算 x16 | 编码 x4 路
  🎬 媒体编码: 4 路活跃  (hevc_qsv)
  🧮 计算线程: 16 个活跃
  ⏱  运行时间: 05:32  剩余: ∞
------------------------------------------------------------------------
  🔥🔥🔥 极高负载 — 核显全力运转！
========================================================================
  按 Ctrl+C 停止测试
```

## ⚠️ 注意事项

1. **散热**：烤机会让核显达到最高功耗，请确保散热正常（风扇正常工作）
2. **温度**：如温度超过 95°C 请立即停止
3. **FFmpeg 必须安装**：媒体压力测试依赖 FFmpeg，请确认 ffmpeg.exe 在 PATH 中
4. **Intel QSV 要求**：需要安装 Intel 核显驱动（Media Feature Pack）
5. **AMD AMF 要求**：需要安装 AMD 显卡驱动（Adrenalin）

## 🔧 常见问题

**Q: 显示"硬件加速不可用，已回退软件编码"**
- A: 确认已安装最新显卡驱动；Intel 用户还需安装 Media Feature Pack

**Q: 找不到 ffmpeg**
- A: 下载 FFmpeg 并将 ffmpeg.exe 放到程序同目录，或将其路径加入系统 PATH

**Q: 程序崩溃**
- A: 尝试使用 `--no-media` 只运行计算压力；或用 `--force-sw` 强制软件编码

**Q: 如何最大化媒体引擎负载**
- A: 使用 `--streams 8 --codec hevc --resolution 3840x2160`

## 📝 版本记录

- v2.0：支持 Intel QSV / AMD AMF / NVIDIA NVENC 自动检测，Windows 专属优化
- v1.0：macOS Apple Silicon 版本

---

*作者：AI 助手 | 仅供测试用途*
