"""
TTS Voice Assistant - PyInstaller Build Script
Day 9: 打包与安装体验

用法:
    python build.py           # 默认单文件模式 (--onefile)
    python build.py --onedir  # 目录模式（降低杀软误报概率）
"""

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("错误：未安装 Pillow，无法生成 .ico 图标。请先运行: pip install Pillow")
    sys.exit(1)


def ensure_icon_ico():
    """确保 resources/icon.ico 存在（按需取用带尺寸后缀的图片）"""
    resources_dir = Path("resources")
    resources_dir.mkdir(exist_ok=True)

    icon_ico = resources_dir / "icon.ico"

    if icon_ico.exists():
        print(f"[Build] 图标已存在: {icon_ico}")
        return str(icon_ico)

    # 按需查找带尺寸后缀的源图片
    for src_name in ["icon_128x128.png", "icon_64x64.png", "icon_32x32.png", "icon.png"]:
        src_path = resources_dir / src_name
        if src_path.exists():
            print(f"[Build] 从 {src_path} 生成 {icon_ico} ...")
            img = Image.open(src_path)
            # 提供多种尺寸以确保 Windows 各场景显示清晰
            img.save(
                icon_ico,
                format="ICO",
                sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
            )
            print(f"[Build] 图标生成成功: {icon_ico}")
            return str(icon_ico)

    print("[Build] 警告: 未找到任何图标源文件，将使用 PyInstaller 默认图标")
    return None


def main():
    # 1. 确保图标
    icon_path = ensure_icon_ico()

    # 2. 构建参数
    mode = "--onedir" if "--onedir" in sys.argv else "--onefile"
    mode_name = "目录模式" if mode == "--onedir" else "单文件模式"
    print(f"[Build] 打包模式: {mode_name}")

    args = [
        "src/main.py",
        "--name=TTS语音助手",
        mode,
        "--windowed",
        "--clean",
        "--noconfirm",
        # hidden imports
        "--hidden-import=edge_tts",
        "--hidden-import=pyttsx3.drivers",
        "--hidden-import=pyttsx3.drivers.sapi5",
        "--hidden-import=sounddevice",
        "--hidden-import=soundfile",
        "--hidden-import=pygame",
        "--hidden-import=numpy",
    ]

    if icon_path:
        args.append(f"--icon={icon_path}")
        args.append("--add-data=resources;resources")

    print("[Build] 开始执行 PyInstaller...")
    print(f"[Build] 参数: {' '.join(args)}")

    import PyInstaller.__main__

    PyInstaller.__main__.run(args)

    print(f"[Build] 打包完成！输出目录: dist/")
    if mode == "--onefile":
        print("[Build] 可执行文件: dist/TTS语音助手.exe")
    else:
        print("[Build] 可执行文件: dist/TTS语音助手/TTS语音助手.exe")
    print("[Build] 提示: --onedir 模式可降低杀毒软件误报概率")


if __name__ == "__main__":
    main()
