# 🔥 v3.6.2 更新说明 (2026-04-24)

## 📋 版本信息
- **版本号**: v3.6.2
- **发布日期**: 2026-04-24
- **前序版本**: v3.6.1 (已废弃)

---

## ✨ 重大改进

### 🚀 完全改用 PowerShell GPU 检测

**原因**:
- WMIC 已被微软弃用 (Windows 10 21H1 起)
- Windows 11 默认不包含 WMIC
- PowerShell Get-CimInstance 更可靠、更现代

**新方法**:
```powershell
Get-CimInstance Win32_VideoController | 
Select-Object Name, AdapterCompatibility, Status, DriverVersion, VideoProcessor |
ConvertTo-Json -Depth 3
```

**优势**:
- ✅ 获取更详细的 GPU 信息
- ✅ 支持混合显卡环境（核显 + 独显）
- ✅ JSON 格式输出，易于解析
- ✅ 显示驱动版本、状态等详细信息
- ✅ 更好的错误处理和诊断

---

## 📊 输出示例

### 成功检测
```
🔍 正在检测 GPU (使用 PowerShell)...
📋 PowerShell 检测到 2 个显卡:
     [0] NVIDIA GeForce RTX 3060
         状态：OK | 驱动：31.0.15.3623
         视频处理器：NVIDIA GeForce RTX 3060
  ✅ 识别：NVIDIA GeForce RTX 3060 (NVIDIA, dedicated)
  
     [1] Intel(R) UHD Graphics 770
         状态：OK | 驱动：31.0.101.4091
         视频处理器：Intel(R) UHD Graphics 770
  ✅ 识别：Intel(R) UHD Graphics 770 (Intel, integrated)

✅ GPU 检测完成，共 2 个显卡
   将使用：NVIDIA GeForce RTX 3060 (NVIDIA)
```

### 检测失败
```
🔍 正在检测 GPU (使用 PowerShell)...
❌ GPU 检测失败：Exception: PowerShell 返回码：1
   详细错误：...
   
   诊断建议:
     1. 打开设备管理器查看显卡状态
     2. 更新显卡驱动 (Intel/AMD/NVIDIA 官网)
     3. 以管理员身份运行程序
     4. 手动运行 PowerShell 命令测试:
        Get-CimInstance Win32_VideoController
```

---

## 🔧 其他修复

### 1. 版本号显示
- ✅ 所有 v3.5 改为 v3.6
- ✅ 文件头、启动信息、监控面板统一

### 2. 错误处理增强
- ✅ 详细的错误类型和堆栈跟踪
- ✅ JSON 解析失败诊断
- ✅ 超时处理（15 秒）
- ✅ CREATE_NO_WINDOW 避免弹出窗口

### 3. 诊断信息
- ✅ 显示每个显卡的详细信息
- ✅ 状态、驱动版本、视频处理器
- ✅ 清晰的识别结果
- ✅ 混合显卡支持

---

## 📥 下载

### GitHub Release
- **URL**: https://github.com/XYXS-ZHXD/igpu-burn-win/releases/tag/v3.6.2
- **文件**: igpu_burn_win_v3.6.2.exe
- **大小**: ~25 MB

### GitHub Actions Artifact
- **URL**: https://github.com/XYXS-ZHXD/igpu-burn-win/actions
- **保留**: 30 天

---

## 🎯 使用建议

### 验证 GPU 检测
```bash
# 运行程序查看 GPU 信息
igpu_burn_win_v3.6.2.exe --info

# 应该看到详细的 GPU 列表和识别结果
```

### 诊断问题
如果仍然无法检测到 GPU：

1. **手动运行 PowerShell 命令**
   ```powershell
   Get-CimInstance Win32_VideoController | 
   Select-Object Name, AdapterCompatibility, Status
   ```

2. **检查设备管理器**
   - Win + X → 设备管理器
   - 查看 "显示适配器" 下的设备
   - 确保没有黄色感叹号

3. **更新显卡驱动**
   - NVIDIA: https://www.nvidia.com/Download/index.aspx
   - AMD: https://www.amd.com/en/support
   - Intel: https://downloadcenter.intel.com/

4. **以管理员身份运行**
   - 右键程序 → 以管理员身份运行

---

## 📊 版本对比

| 功能 | v3.6 | v3.6.2 |
|------|------|--------|
| GPU 检测方法 | WMIC | PowerShell |
| 混合显卡支持 | ⚠️ 部分 | ✅ 完整 |
| 详细信息显示 | ❌ | ✅ 驱动/状态/处理器 |
| 错误诊断 | ⚠️ 基础 | ✅ 详细堆栈跟踪 |
| Windows 11 兼容 | ❌ | ✅ |
| 版本号显示 | ⚠️ 混乱 | ✅ 统一 v3.6.2 |

---

## 🐛 已知问题

### 待修复
- [ ] 某些精简版 Windows 可能没有 PowerShell（罕见）
- [ ] 需要 .NET Framework 4.5+（通常已预装）

### 临时方案
如果 PowerShell 也失败，请：
1. 运行 `sfc /scannow` 修复系统文件
2. 确保 .NET Framework 已安装
3. 联系作者获取帮助

---

## 🙏 致谢

感谢用户反馈 WMIC 弃用问题！
v3.6.2 完全改用 PowerShell，确保长期兼容性。

---

**最后更新**: 2026-04-24  
**版本**: v3.6.2  
**作者**: XYXS-ZHXD
