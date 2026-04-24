# 📦 EXE 编译说明

## 🎯 当前状态

✅ **GitHub Actions 自动构建已配置**
- 工作流文件：`.github/workflows/build_exe.yml`
- 触发条件：推送到 main 分支 / 创建 v* 标签 / 手动触发
- 输出位置：
  - GitHub Release 附件（标签推送时）
  - `releases/` 目录（main 分支推送时）
  - Workflow Artifact（保留 30 天）

---

## 🚀 自动构建（推荐）

### 触发构建

**方法 1: 推送到 main 分支**
```bash
git push origin main
```

**方法 2: 创建版本标签**
```bash
git tag v3.6
git push origin v3.6
```

**方法 3: GitHub 网页手动触发**
1. 访问：https://github.com/XYXS-ZHXD/igpu-burn-win/actions
2. 选择 "🔥 Build Windows EXE" 工作流
3. 点击 "Run workflow"
4. 选择分支后点击 "Run workflow"

### 下载 EXE

**构建完成后（约 2-5 分钟）：**

**选项 A: 从 Release 下载（标签推送）**
1. 访问：https://github.com/XYXS-ZHXD/igpu-burn-win/releases
2. 找到对应版本
3. 下载 `igpu_burn_win.exe`

**选项 B: 从 Artifact 下载（所有构建）**
1. 访问：https://github.com/XYXS-ZHXD/igpu-burn-win/actions
2. 点击最近的构建
3. 在 "Artifacts" 部分下载 `igpu_burn_win`
4. 解压后得到 `igpu_burn_win.exe`

**选项 C: 从仓库下载（main 分支构建）**
1. 访问：https://github.com/XYXS-ZHXD/igpu-burn-win/tree/main/releases
2. 下载 `igpu_burn_win.exe`

---

## 💻 本地手动编译

### 环境要求

- **操作系统**: Windows 10/11
- **Python**: 3.9 或更高版本
- **依赖包**: PyInstaller, numpy, psutil, PyOpenGL, glfw

### 编译步骤

**1. 安装 Python 依赖**
```bash
pip install pyinstaller numpy psutil PyOpenGL PyOpenGL-accelerate glfw
```

**2. 运行构建脚本**
```bash
build_exe.bat
```

或者手动执行：
```bash
pyinstaller --onefile --console --name "igpu_burn_win" --hidden-import numpy --hidden-import psutil --collect-all numpy igpu_burn_win.py
```

**3. 获取 EXE**
- 输出位置：`dist/igpu_burn_win.exe`
- 文件大小：约 25-30 MB

**4. （可选）添加 FFmpeg**
- 下载：https://github.com/BtbN/FFmpeg-Builds/releases
- 下载 `ffmpeg-master-latest-win64-gpl.zip`
- 解压后将 `ffmpeg.exe` 放到 `dist/` 目录

---

## 📊 构建配置详情

### PyInstaller 参数

```yaml
--onefile           # 单文件 EXE
--console           # 控制台程序
--name igpu_burn_win
--hidden-import numpy
--hidden-import psutil
--collect-all numpy
```

### 依赖包

```txt
pyinstaller         # EXE 打包工具
numpy               # 矩阵计算
psutil              # 系统监控
PyOpenGL            # OpenGL 支持（备用）
PyOpenGL-accelerate # OpenGL 加速（可选）
glfw                # 窗口管理（备用）
```

### 构建时间

- **GitHub Actions**: 2-5 分钟
- **本地编译**: 1-3 分钟（取决于机器性能）

---

## 🔧 故障排除

### 问题 1: GitHub Actions 构建失败

**症状**: 构建显示红色 ❌

**解决**:
1. 点击构建查看日志
2. 检查错误信息
3. 常见问题：
   - 依赖包安装失败 → 检查网络
   - PyInstaller 错误 → 检查 Python 版本
   - 内存不足 → 使用更大内存的 Runner

### 问题 2: 本地编译 EXE 无法运行

**症状**: 双击无反应或报错

**解决**:
1. 以管理员身份运行
2. 检查 Windows Defender 是否拦截
3. 在命令行运行查看详细错误：
   ```bash
   igpu_burn_win.exe --info
   ```

### 问题 3: EXE 文件过大

**症状**: 超过 50 MB

**解决**:
1. 使用 `--onefile` 而非 `--onedir`
2. 移除不必要的依赖
3. 使用 UPX 压缩（可选）：
   ```bash
   pyinstaller --upx-dir=upx ...
   ```

---

## 📥 当前版本 EXE

### v3.6 (最新版本)

- **构建状态**: 🔄 正在构建中...
- **预计完成**: 2-5 分钟
- **下载链接**: 
  - Release: https://github.com/XYXS-ZHXD/igpu-burn-win/releases/tag/v3.6
  - Actions: https://github.com/XYXS-ZHXD/igpu-burn-win/actions

### v3.5 (前一版本)

- **状态**: ✅ 已发布
- **下载**: https://github.com/XYXS-ZHXD/igpu-burn-win/releases/tag/v3.5

---

## 🎯 最佳实践

1. **使用自动构建** - 省时省力，环境一致
2. **标签发布** - 创建正式版本时使用标签
3. **测试后再发布** - 先在本地测试 EXE 功能
4. **保留 Artifact** - 下载后本地备份

---

**最后更新**: 2026-04-24  
**版本**: v3.6  
**作者**: XYXS-ZHXD
