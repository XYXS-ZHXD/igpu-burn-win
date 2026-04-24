# 📥 下载 v3.6 EXE

## ✅ 最新版本

**版本**: v3.6  
**发布日期**: 2026-04-24  
**文件大小**: 24.89 MB  
**SHA256**: `326d85be0846ba2e6bae8288b411a6711531c7645d9203681e94caff54fecaf2`

---

## 🔗 下载链接

### 方式 1: GitHub Release（推荐）
**直接下载**: https://github.com/XYXS-ZHXD/igpu-burn-win/releases/download/v3.6/igpu_burn_win_v3.6.exe

### 方式 2: GitHub Actions Artifact
1. 访问：https://github.com/XYXS-ZHXD/igpu-burn-win/actions/runs/24886885252
2. 点击 "igpu_burn_win" Artifact
3. 下载并解压

---

## 🚀 快速使用

### 基本用法
```bash
# 下载后直接双击运行
igpu_burn_win_v3.6.exe

# 或使用命令行
igpu_burn_win_v3.6.exe --info
```

### 常用命令
```bash
# 查看所有 GPU 信息
igpu_burn_win.exe --info

# 默认模式（自动选择最强 GPU）
igpu_burn_win.exe

# 强制使用 NVIDIA 独显
igpu_burn_win.exe --gpu nvidia

# 强制使用 Intel 核显
igpu_burn_win.exe --gpu intel

# 8 路 4K HEVC 编码（需要 ffmpeg.exe）
igpu_burn_win.exe --streams 8 --codec hevc

# 限时 10 分钟测试
igpu_burn_win.exe --duration 600

# 查看帮助
igpu_burn_win.exe --help
```

---

## 📋 系统要求

- **操作系统**: Windows 10/11 (64 位)
- **DirectX**: DirectX 11（Windows 自带）
- **显卡驱动**: 建议更新到最新版本
- **内存**: 至少 4GB RAM
- **磁盘空间**: 至少 100MB 可用空间

---

## 🔧 可选依赖

### FFmpeg（用于硬件编码测试）

**下载**: https://github.com/BtbN/FFmpeg-Builds/releases

**安装步骤**:
1. 下载 `ffmpeg-master-latest-win64-gpl.zip`
2. 解压后将 `ffmpeg.exe` 放到 `igpu_burn_win.exe` 同目录
3. 程序启动时会提示 "✅ 找到同目录 ffmpeg.exe"

**作用**:
- NVIDIA NVENC 硬件编码
- AMD AMF 硬件编码
- Intel QSV 硬件编码（需要特殊编译的 FFmpeg）

---

## ✅ 验证下载

### 检查文件完整性
```powershell
# PowerShell
Get-FileHash igpu_burn_win_v3.6.exe -Algorithm SHA256
```

应该输出：
```
326d85be0846ba2e6bae8288b411a6711531c7645d9203681e94caff54fecaf2
```

### 验证 GPU 是否在工作

**方法 1: 查看启动日志**
```
应该看到:
✅ DirectX 11 GPU 烤机线程已启动 (worker=0, buffer=16MB)

不应该看到:
⚠️  WARNING: DirectX 11 GPU 烤机初始化失败！
```

**方法 2: 任务管理器**
1. 打开任务管理器 → GPU 标签页
2. 运行程序
3. GPU 利用率应该飙升到 80-100%

**方法 3: 命令行工具**
```bash
# NVIDIA
nvidia-smi

# AMD
radeontop

# Intel
intel_gpu_top
```

---

## 🐛 常见问题

### Q1: 双击无反应
**A**: 以管理员身份运行，或在命令行运行查看详细错误

### Q2: GPU 利用率为 0%
**A**: 
1. 查看启动日志是否有 DX11 错误
2. 更新显卡驱动
3. 运行 `sfc /scannow` 修复系统文件

### Q3: 缺少 DLL 错误
**A**: 这是单文件 EXE，所有依赖都已打包。如果报错，可能是：
- Windows Defender 拦截 → 添加排除项
- 系统文件损坏 → 运行 `sfc /scannow`

### Q4: 温度/功耗显示 N/A
**A**: 
- NVIDIA: 确保安装了 nvidia-smi
- AMD: 确保安装了 AMD 驱动
- Intel: 部分核显不支持功耗监控

---

## 📊 v3.6 更新内容

### 新增功能
- ✅ GPU 活动验证机制
- ✅ 增强错误提示和诊断
- ✅ 启动/停止日志输出
- ✅ 自动 CPU 备用方案

### 技术改进
- 新增 `DX11_AVAILABLE` 全局标志
- 新增 `dx_active`, `dx_frames`, `dx_errors` 统计
- 详细的错误原因和修复建议

---

## 🔗 相关链接

- **GitHub 仓库**: https://github.com/XYXS-ZHXD/igpu-burn-win
- **Release 页面**: https://github.com/XYXS-ZHXD/igpu-burn-win/releases/tag/v3.6
- **问题反馈**: https://github.com/XYXS-ZHXD/igpu-burn-win/issues
- **更新日志**: https://github.com/XYXS-ZHXD/igpu-burn-win/blob/main/RELEASE_v3.6.md

---

**最后更新**: 2026-04-24  
**版本**: v3.6  
**作者**: XYXS-ZHXD
