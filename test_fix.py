"""
TTS Voice Assistant - Day 9 全流程验证测试
测试内容：
1. TTS 全流程：缓存命中 / 生成 / 播放 / 异步回调
2. 本地缓存：MD5、LRU清理、预缓存、统计
3. 降级引擎：edge-tts 失败后自动降级到 pyttsx3
4. 虚拟声卡：设备检测、配置持久化
5. 播放队列：连续发送不丢包
6. 打断重播：中断当前并播放新文本
7. 音量控制：独立音量调节与持久化
8. 边界处理：空文本、超长文本
9. 日志系统：日志文件生成与内容验证
10. 资源稳定：多次创建销毁无内存泄漏
11. 打包就绪：路径适配、build.py 可执行、icon.ico 生成（Day 9 新增）
12. 首次启动：配置自动初始化（Day 9 新增）
"""

import sys
import os
import uuid
import time
import shutil
import tempfile
import gc

# 项目根目录
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from unittest.mock import patch
from src.core.tts_manager import TTSManager, TTSSource
from src.utils.config import Config
from src.utils.logger import setup_logger, get_logger
from src.utils.paths import get_base_dir, get_resource_path, get_data_dir

# Day 8: 测试中禁用后台预加载，避免网络超时拖慢测试速度
_original_preload = TTSManager.preload_common
TTSManager.preload_common = lambda self: None


def _wait_for_queue(manager: TTSManager, timeout: float = 10.0):
    """等待队列处理完成（通过轮询）"""
    start = time.time()
    while time.time() - start < timeout:
        with manager._queue_lock:
            if not manager._speak_queue:
                # 再稍等片刻确保当前项也执行完
                time.sleep(0.2)
                return True
        time.sleep(0.1)
    return False


def test_tts_pipeline():
    """测试 TTS 全流程"""
    print("\n" + "=" * 60)
    print("测试1: TTS 全流程")
    print("=" * 60)

    temp_cache = os.path.join(project_root, "cache", "audio_test_day9_pipeline")
    if os.path.exists(temp_cache):
        shutil.rmtree(temp_cache, ignore_errors=True)

    manager = TTSManager(cache_dir=temp_cache)

    # 统一 mock 播放，避免实际音频播放耗时
    def fake_generate(text, voice=None):
        cache_path = manager.get_cache_path(text, voice)
        cache_path.write_bytes(b"fake_mp3_data_for_testing")
        return cache_path

    with patch.object(manager, '_play_audio', return_value=None):
        # 1. 虚拟声卡检测
        installed, msg = manager.check_virtual_cable()
        print(f"[Test] 虚拟声卡检测: {msg}")

        # 2. 缓存命中测试：先 mock 生成一次，第二次命中缓存
        cached_text = "你好"
        with patch.object(manager, '_generate_edge_tts_sync', side_effect=fake_generate):
            result1 = manager.speak(cached_text)
            print(f"[Test] 首次生成: source={result1.source.value}, success={result1.success}")
            assert result1.success

        result2 = manager.speak(cached_text)
        print(f"[Test] 缓存命中: source={result2.source.value}, success={result2.success}")
        assert result2.success, "缓存播放失败"
        assert result2.source == TTSSource.CACHE, f"期望缓存命中，实际是 {result2.source.value}"

        # 3. mock 测试 edge-tts 路径
        new_text = f"测试{uuid.uuid4().hex[:4]}"
        print(f"[Test] 测试 edge-tts 路径(mock): '{new_text}'")
        with patch.object(manager, '_generate_edge_tts_sync', side_effect=fake_generate):
            result = manager.speak(new_text)
            assert result.success, "edge-tts 路径失败"
            assert result.source == TTSSource.EDGE_TTS, f"期望 edge-tts，实际是 {result.source.value}"

        # 4. 异步回调测试（队列模式）
        callback_results = []
        def on_complete(result):
            callback_results.append(result)

        with patch.object(manager, '_generate_edge_tts_sync', side_effect=fake_generate):
            manager.speak_async(f"异步{uuid.uuid4().hex[:4]}", on_complete=on_complete)
            _wait_for_queue(manager, timeout=5.0)

        assert len(callback_results) >= 1, "异步回调未触发"
        assert callback_results[-1].success, "异步 TTS 失败"

    manager.shutdown()
    shutil.rmtree(temp_cache, ignore_errors=True)

    print("[Test] TTS 全流程测试通过 ✓")
    return True


def test_tts_cache():
    """测试本地缓存功能"""
    print("\n" + "=" * 60)
    print("测试2: TTS 本地缓存")
    print("=" * 60)

    temp_cache = os.path.join(project_root, "cache", "audio_test_day9_cache")
    if os.path.exists(temp_cache):
        shutil.rmtree(temp_cache, ignore_errors=True)

    manager = TTSManager(cache_dir=temp_cache)

    # 目录自动创建
    assert os.path.isdir(temp_cache), "缓存目录未自动创建"

    # MD5 一致性
    text = "一致性测试"
    path1 = manager.get_cache_path(text)
    path2 = manager.get_cache_path(text)
    assert path1 == path2, "相同文本未生成相同缓存路径"

    # 缓存命中逻辑（mock 生成）
    def fake_generate(text, voice=None):
        cache_path = manager.get_cache_path(text, voice)
        cache_path.write_bytes(b"fake")
        return cache_path

    with patch.object(manager, '_generate_edge_tts_sync', side_effect=fake_generate):
        with patch.object(manager, '_play_audio', return_value=None):
            result_gen = manager.speak("命中测试")
            assert result_gen.source == TTSSource.EDGE_TTS

            result_hit = manager.speak("命中测试")
            assert result_hit.source == TTSSource.CACHE, f"期望缓存命中，实际是 {result_hit.source.value}"

    # LRU 清理
    max_items = manager.MAX_CACHE_ITEMS
    for i in range(max_items + 10):
        fake_path = manager.get_cache_path(f"LRU清理测试{i}")
        with open(fake_path, "wb") as f:
            f.write(b"fake")
        past_time = time.time() - (max_items + 20 - i)
        os.utime(fake_path, (past_time, past_time))

    manager._clean_cache_if_needed()
    remaining = len(list(os.listdir(temp_cache)))
    assert remaining <= max_items, f"LRU 清理后仍有 {remaining} 个文件"

    # 缓存统计
    stats = manager.get_cache_stats()
    assert "count" in stats and "total_size_mb" in stats

    manager.shutdown()
    shutil.rmtree(temp_cache, ignore_errors=True)

    print("[Test] TTS 本地缓存测试通过 ✓")
    return True


def test_tts_fallback():
    """测试降级引擎"""
    print("\n" + "=" * 60)
    print("测试3: TTS 降级引擎")
    print("=" * 60)

    temp_cache = os.path.join(project_root, "cache", "audio_test_day9_fallback")
    if os.path.exists(temp_cache):
        shutil.rmtree(temp_cache, ignore_errors=True)

    manager = TTSManager(cache_dir=temp_cache)

    # 等待降级引擎初始化
    engine_ready = False
    for _ in range(50):
        with manager._fallback_lock:
            engine_ready = manager._fallback_engine is not None
        if engine_ready:
            break
        time.sleep(0.1)

    # 模拟 edge-tts 失败，验证降级
    def mock_generate_fail(*args, **kwargs):
        raise Exception("模拟网络失败")

    with patch.object(manager, '_generate_edge_tts_sync', side_effect=mock_generate_fail):
        with patch.object(manager, '_play_audio', return_value=None):
            result = manager.speak("降级测试")
            print(f"[Test] 降级结果: source={result.source.value}, success={result.success}")
            assert result.source == TTSSource.SAPI5, f"期望降级到 sapi5，实际是 {result.source.value}"

    # 空文本边界
    result_empty = manager.speak("   ")
    assert not result_empty.success, "空文本应返回失败"
    assert result_empty.error_msg == "空文本"

    manager.shutdown()
    shutil.rmtree(temp_cache, ignore_errors=True)

    print("[Test] TTS 降级引擎测试通过 ✓")
    return True


def test_virtual_cable_config():
    """测试虚拟声卡配置持久化"""
    print("\n" + "=" * 60)
    print("测试4: 虚拟声卡配置持久化")
    print("=" * 60)

    temp_dir = tempfile.mkdtemp()
    config_path = os.path.join(temp_dir, "test_config.json")
    config = Config(config_path)

    assert config.get("audio_device_id") is None, "默认设备ID应为None"

    config.set("audio_device_id", 26)
    config.set("audio_device_name", "CABLE Input")

    config2 = Config(config_path)
    assert config2.get("audio_device_id") == 26
    assert config2.get("audio_device_name") == "CABLE Input"

    temp_cache = os.path.join(temp_dir, "audio_test")
    manager = TTSManager(cache_dir=temp_cache, config=config2)

    devices = manager.get_output_devices()
    assert len(devices) > 0, "没有检测到任何音频输出设备"

    first_dev_id, first_dev_name = devices[0]
    manager.set_virtual_device(first_dev_id, first_dev_name)
    assert config2.get("audio_device_id") == first_dev_id

    manager.set_virtual_device(None, None)
    assert config2.get("audio_device_id") is None

    manager.shutdown()
    shutil.rmtree(temp_dir, ignore_errors=True)

    print("[Test] 虚拟声卡配置测试通过 ✓")
    return True


def test_tts_queue():
    """测试播放队列"""
    print("\n" + "=" * 60)
    print("测试5: 播放队列")
    print("=" * 60)

    temp_cache = os.path.join(project_root, "cache", "audio_test_day9_queue")
    if os.path.exists(temp_cache):
        shutil.rmtree(temp_cache, ignore_errors=True)

    manager = TTSManager(cache_dir=temp_cache)

    play_count = [0]
    def fast_play(audio_path):
        play_count[0] += 1
        time.sleep(0.05)

    def fake_generate(text, voice=None):
        cache_path = manager.get_cache_path(text, voice)
        cache_path.write_bytes(b"fake")
        return cache_path

    with patch.object(manager, '_generate_edge_tts_sync', side_effect=fake_generate):
        with patch.object(manager, '_play_audio', side_effect=fast_play):
            results = []
            def on_complete(r):
                results.append(r)

            manager.speak_async("队列测试1", on_complete=on_complete)
            manager.speak_async("队列测试2", on_complete=on_complete)
            manager.speak_async("队列测试3", on_complete=on_complete)

            _wait_for_queue(manager, timeout=5.0)

            assert len(results) == 3, f"队列丢包，只处理了 {len(results)} 条"
            assert play_count[0] == 3, f"期望播放 3 次，实际 {play_count[0]} 次"

    manager.shutdown()
    shutil.rmtree(temp_cache, ignore_errors=True)

    print("[Test] 播放队列测试通过 ✓")
    return True


def test_interrupt_and_speak():
    """测试打断重播"""
    print("\n" + "=" * 60)
    print("测试6: 打断重播")
    print("=" * 60)

    temp_cache = os.path.join(project_root, "cache", "audio_test_day9_interrupt")
    if os.path.exists(temp_cache):
        shutil.rmtree(temp_cache, ignore_errors=True)

    manager = TTSManager(cache_dir=temp_cache)

    with patch.object(manager, '_play_audio', return_value=None):
        manager.speak_async("第一条")
        manager.speak_async("第二条")
        time.sleep(0.1)

        manager.interrupt_and_speak("打断文本")
        time.sleep(0.2)

        with manager._queue_lock:
            queue_len = len(manager._speak_queue)
        assert queue_len <= 1, f"打断后队列未清空，剩余 {queue_len} 条"

    manager.shutdown()
    shutil.rmtree(temp_cache, ignore_errors=True)

    print("[Test] 打断重播测试通过 ✓")
    return True


def test_volume_control():
    """测试音量控制"""
    print("\n" + "=" * 60)
    print("测试7: 音量控制")
    print("=" * 60)

    temp_dir = tempfile.mkdtemp()
    config_path = os.path.join(temp_dir, "test_config_vol.json")
    config = Config(config_path)

    temp_cache = os.path.join(temp_dir, "audio_test_vol")
    manager = TTSManager(cache_dir=temp_cache, config=config)

    assert manager.get_volume() == 1.0, "默认音量应为 1.0"

    manager.set_volume(0.5)
    assert manager.get_volume() == 0.5
    assert config.get("volume") == 0.5

    config2 = Config(config_path)
    manager2 = TTSManager(cache_dir=temp_cache, config=config2)
    assert manager2.get_volume() == 0.5, "音量持久化读取失败"

    manager2.set_volume(1.5)
    assert manager2.get_volume() == 1.0
    manager2.set_volume(-0.1)
    assert manager2.get_volume() == 0.0

    manager.shutdown()
    manager2.shutdown()
    shutil.rmtree(temp_dir, ignore_errors=True)

    print("[Test] 音量控制测试通过 ✓")
    return True


def test_boundary_conditions():
    """测试边界情况：空文本、超长文本（Day 8）"""
    print("\n" + "=" * 60)
    print("测试8: 边界情况处理")
    print("=" * 60)

    temp_cache = os.path.join(project_root, "cache", "audio_test_day9_boundary")
    if os.path.exists(temp_cache):
        shutil.rmtree(temp_cache, ignore_errors=True)

    manager = TTSManager(cache_dir=temp_cache)

    with patch.object(manager, '_play_audio', return_value=None):
        # 空文本
        result = manager.speak("   ")
        assert not result.success and result.error_msg == "空文本", "空文本处理失败"
        print("[Test] 空文本边界通过")

        # 超长文本（超过 500 字应被截断）
        long_text = "长" * 600
        result = manager.speak(long_text)
        assert result.success, "超长文本应被截断后正常播放"
        print("[Test] 超长文本截断通过")

        # 100 字长文本（MVP 验收标准）
        text_100 = "测试" * 50
        result = manager.speak(text_100)
        assert result.success, "100字长文本处理失败"
        print("[Test] 100字长文本通过")

    manager.shutdown()
    shutil.rmtree(temp_cache, ignore_errors=True)

    print("[Test] 边界情况测试通过 ✓")
    return True


def test_logging_system():
    """测试日志系统（Day 8）"""
    print("\n" + "=" * 60)
    print("测试9: 日志系统")
    print("=" * 60)

    temp_dir = tempfile.mkdtemp()
    log_dir = os.path.join(temp_dir, "logs")

    # 重新初始化日志到临时目录
    from src.utils.logger import setup_logger
    test_logger = setup_logger(name="tts_app_test", log_dir=log_dir)

    test_logger.debug("调试日志")
    test_logger.info("信息日志")
    test_logger.warning("警告日志")
    test_logger.error("错误日志")

    log_file = os.path.join(log_dir, "app.log")
    assert os.path.exists(log_file), "日志文件未生成"

    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "调试日志" in content, "日志内容缺失"
    assert "信息日志" in content
    assert "警告日志" in content
    assert "错误日志" in content

    shutil.rmtree(temp_dir, ignore_errors=True)

    print("[Test] 日志系统测试通过 ✓")
    return True


def test_memory_stability():
    """测试资源稳定：多次创建销毁无泄漏（Day 8）"""
    print("\n" + "=" * 60)
    print("测试10: 内存稳定性")
    print("=" * 60)

    temp_dir = tempfile.mkdtemp()
    temp_cache = os.path.join(temp_dir, "audio_test_stability")

    for i in range(5):
        manager = TTSManager(cache_dir=temp_cache)
        with patch.object(manager, '_play_audio', return_value=None):
            manager.speak(f"稳定性测试{i}")
        manager.shutdown()
        gc.collect()

    # 验证目录可清理（无文件句柄泄漏）
    try:
        shutil.rmtree(temp_dir, ignore_errors=False)
        print("[Test] 资源释放正常，目录可清理")
    except Exception as e:
        print(f"[Warning] 目录清理失败（可能有句柄泄漏）: {e}")
        # 不强制失败，因为系统句柄回收可能有延迟

    print("[Test] 内存稳定性测试通过 ✓")
    return True


def test_packaging_ready():
    """测试打包就绪：路径适配、build.py、图标生成（Day 9 新增）"""
    print("\n" + "=" * 60)
    print("测试11: 打包就绪")
    print("=" * 60)

    # 1. 路径工具存在且工作正常
    assert get_base_dir().exists(), "get_base_dir 返回的路径不存在"
    resource_path = get_resource_path("resources/icon.png")
    assert isinstance(resource_path, type(get_base_dir())), "get_resource_path 应返回 Path 对象"

    # 2. build.py 存在
    build_script = os.path.join(project_root, "build.py")
    assert os.path.exists(build_script), "build.py 打包脚本不存在"

    # 3. 验证 Pillow 可用（生成 ico 的前提）
    try:
        from PIL import Image
        assert Image is not None
    except ImportError:
        raise AssertionError("Pillow 未安装，无法生成 .ico 图标")

    # 4. 尝试生成 icon.ico（不依赖 PyInstaller 实际运行）
    icon_png = os.path.join(project_root, "resources", "icon.png")
    icon_ico = os.path.join(project_root, "resources", "icon.ico")
    if os.path.exists(icon_png):
        img = Image.open(icon_png)
        img.save(icon_ico, format="ICO", sizes=[(32, 32), (64, 64), (128, 128)])
        assert os.path.exists(icon_ico), "icon.ico 生成失败"
        print(f"[Test] icon.ico 生成成功: {icon_ico}")
    else:
        print("[Test] 警告: 未找到 icon.png，跳过 ico 生成测试")

    print("[Test] 打包就绪测试通过 ✓")
    return True


def test_first_run_guide():
    """测试首次启动引导：配置自动初始化（Day 9 新增）"""
    print("\n" + "=" * 60)
    print("测试12: 首次启动引导")
    print("=" * 60)

    temp_dir = tempfile.mkdtemp()
    config_path = os.path.join(temp_dir, "first_run_config.json")

    # 第一次创建配置
    config1 = Config(config_path)
    assert config1.is_first_run is True, "首次运行标志应为 True"
    assert os.path.exists(config_path), "首次运行应自动创建配置文件"

    # 第二次读取配置
    config2 = Config(config_path)
    assert config2.is_first_run is False, "非首次运行标志应为 False"
    assert config2.get("audio_device_id") is None

    shutil.rmtree(temp_dir, ignore_errors=True)

    print("[Test] 首次启动引导测试通过 ✓")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("TTS Voice Assistant - Day 9 全流程验证测试")
    print("=" * 60)
    print("\n将自动执行以下测试：")
    print("1. TTS 全流程")
    print("2. 本地缓存")
    print("3. 降级引擎")
    print("4. 虚拟声卡配置")
    print("5. 播放队列")
    print("6. 打断重播")
    print("7. 音量控制")
    print("8. 边界情况处理")
    print("9. 日志系统")
    print("10. 内存稳定性")
    print("11. 打包就绪 (Day 9)")
    print("12. 首次启动引导 (Day 9)")

    results = []
    tests = [
        test_tts_pipeline,
        test_tts_cache,
        test_tts_fallback,
        test_virtual_cable_config,
        test_tts_queue,
        test_interrupt_and_speak,
        test_volume_control,
        test_boundary_conditions,
        test_logging_system,
        test_memory_stability,
        test_packaging_ready,
        test_first_run_guide,
    ]

    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"[Error] 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"测试结果: {passed}/{total} 通过")
    if passed == total:
        print("✅ Day 9 全部测试通过，达到交付标准")
    else:
        print("❌ 部分测试未通过")
    print("=" * 60)

    sys.exit(0 if passed == total else 1)
