# TTS 语音助手

一个基于 PyQt6 的 Windows 桌面 TTS（文字转语音）工具，支持全局热键唤出悬浮窗输入文字并播放语音。

## 特性

- 🎙️ **Edge TTS 主引擎**：高质量在线语音合成
- 🔥 **全局热键**：`Ctrl + Shift + T` 一键唤出悬浮输入窗
- 🔊 **音频设备切换**：支持虚拟声卡（VB-CABLE）自动检测与手动选择
- 💾 **本地缓存**：常用语预加载，命中时延迟 < 200ms
- 🛡️ **三级降级**：缓存 → Edge TTS → 系统 TTS（pyttsx3/SAPI5）
- ⚡ **播放队列**：连续发送不丢包，支持打断重播
- 🎚️ **音量控制**：独立音量调节与持久化

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行（开发模式）
python src/main.py

# 3. 打包（可选）
python build.py
```

首次运行时会自动在项目根目录生成 `config.json`，用于保存用户的音频设备、音量、热键等设置。

> 若需自定义默认配置，可复制 `config.example.json` 为 `config.json` 后再启动。

## 文档

- [安装指南](./INSTALL.md)
- [快速入门](./QUICKSTART.md)
- [已知问题](./KNOWN_ISSUES.md)

## 项目结构

```
├── src/              # 源代码
│   ├── core/         # TTS 管理器、热键管理器
│   ├── ui/           # 悬浮窗口
│   └── utils/        # 配置、日志、路径工具
├── resources/        # 图标资源
├── requirements.txt  # Python 依赖
├── build.py          # PyInstaller 打包脚本
└── test_fix.py       # 全流程验证测试
```

## 许可证

MIT
