"""非英文文件名处理单元测试

验证视频处理流水线对包含中文、日文等非英文字符的文件名的兼容性。

根因（修复前）：
  core.utils._run_ffprobe 使用 ``subprocess.run(..., text=True)`` 但未显式指定
  encoding。``text=True`` 会以 ``locale.getpreferredencoding()`` 解码 ffprobe 的
  stdout——ffprobe 输出 UTF-8 JSON（含回显的输入文件名），在中文 Windows 上
  locale 为 cp936/gbk，遇到非英文字节即抛 UnicodeDecodeError，导致非英文文件名
  的视频在 validate_video_file 验证阶段就被错误拒绝，流水线根本无法启动。

修复：
  显式指定 ``encoding="utf-8", errors="replace"``，跨平台一致地以 UTF-8 解码
  ffprobe 输出；其余环节（Python open/os.makedirs/json 的 ensure_ascii=False/
  subprocess 列表参数/cv2.VideoCapture）本身已正确处理 Unicode 路径。

测试覆盖：
  - _run_ffprobe 显式使用 utf-8 编码（mock subprocess.run 断言 kwargs）
  - _run_ffprobe 正确解析含中文/日文文件名的 JSON（mock）
  - validate_video_file / validate_output_video 对非英文文件名不抛异常（mock）
  - 真实 ffprobe 集成测试：用 ffmpeg 生成中文/日文文件名视频并验证（需工具）
  - 流水线各环节路径构造保留 Unicode（get_output_dir / prepare_output_path）
  - JSON / 文本文件读写对中文内容往返一致
  - 回归：纯英文文件名处理不受影响
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from unittest import mock

import pytest

from arknights_video_pipeline.core import utils as core_utils
from arknights_video_pipeline.core.config import ConfigManager
from arknights_video_pipeline.core.utils import (
    PROJECT_ROOT,
    _run_ffprobe,
    read_json_file,
    write_json_file,
    write_text_file,
    validate_video_file,
    validate_output_video,
)
from arknights_video_pipeline.core.video_compose_common import prepare_output_path


# ── 测试用非英文文件名样本 ─────────────────────────────────

NON_ASCII_NAMES = [
    pytest.param("测试视频.mp4", id="chinese"),
    pytest.param("動画01.mp4", id="japanese"),
    pytest.param("테스트.mp4", id="korean"),
    pytest.param("视频_動画_비디오.mp4", id="mixed_cjk"),
    pytest.param("Видео.mp4", id="cyrillic"),
]


def _fake_probe(filename: str) -> str:
    """构造一份含非英文文件名的 ffprobe JSON 输出（str，模拟 utf-8 解码后）"""
    return json.dumps({
        "streams": [
            {"codec_type": "video", "width": 160, "height": 120,
             "codec_name": "h264", "r_frame_rate": "15/1"},
        ],
        "format": {
            "filename": filename,
            "duration": "1.000000",
            "size": "12345",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        },
    }, ensure_ascii=False)


class _CompletedProcess:
    """轻量的 subprocess.CompletedProcess 替身"""
    def __init__(self, returncode: int, stdout: str, stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── _run_ffprobe 编码修复 ───────────────────────────────────


class TestRunFfprobeEncoding:
    """验证 _run_ffprobe 显式以 UTF-8 解码 ffprobe 输出"""

    def test_uses_utf8_encoding(self) -> None:
        """subprocess.run 被调用时显式传入 encoding='utf-8' 与 errors='replace'"""
        with mock.patch.object(core_utils.subprocess, "run") as m_run:
            m_run.return_value = _CompletedProcess(0, _fake_probe("test.mp4"))
            _run_ffprobe("test.mp4")
        assert m_run.call_count == 1
        kwargs = m_run.call_args.kwargs
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "replace"
        assert kwargs.get("text") is True

    def test_passes_path_as_list_arg_not_shell(self) -> None:
        """video_path 作为列表参数传入（shell=False），避免 shell 注入与编码问题"""
        with mock.patch.object(core_utils.subprocess, "run") as m_run:
            m_run.return_value = _CompletedProcess(0, _fake_probe("测试.mp4"))
            _run_ffprobe("测试.mp4")
        args = m_run.call_args.args[0]
        assert isinstance(args, list)
        assert "测试.mp4" in args
        assert m_run.call_args.kwargs.get("shell") in (None, False)

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_parses_non_ascii_filename_json(self, name: str) -> None:
        """含非英文文件名的 ffprobe JSON 被正确解析，文件名字段原样保留"""
        with mock.patch.object(core_utils.subprocess, "run") as m_run:
            m_run.return_value = _CompletedProcess(0, _fake_probe(name))
            probe = _run_ffprobe(name)
        assert probe["format"]["filename"] == name
        assert probe["streams"][0]["codec_type"] == "video"

    def test_locale_independent_explicit_encoding(self) -> None:
        """即使系统 locale 为 cp936，显式 encoding='utf-8' 仍优先

        模拟中文 Windows：locale.getpreferredencoding() 返回 'cp936'。
        由于显式指定 encoding='utf-8'，subprocess 不依赖 locale，UTF-8 JSON
        被正确解码——这正是修复的核心。utils.py 无需导入 locale（修复本身
        不引用它），故直接 patch 全局 locale 模块即可证明 locale-无关性。
        """
        import locale as _locale
        with mock.patch.object(_locale, "getpreferredencoding", return_value="cp936"):
            with mock.patch.object(core_utils.subprocess, "run") as m_run:
                m_run.return_value = _CompletedProcess(0, _fake_probe("测试.mp4"))
                probe = _run_ffprobe("测试.mp4")
        assert probe["format"]["filename"] == "测试.mp4"
        # 显式 encoding 仍为 utf-8，未被 locale 影响
        assert m_run.call_args.kwargs.get("encoding") == "utf-8"

    def test_nonzero_returncode_raises_validation_error(self) -> None:
        """ffprobe 返回非零时抛 VideoValidationError，而非编码异常"""
        from arknights_video_pipeline.core.exceptions import VideoValidationError
        with mock.patch.object(core_utils.subprocess, "run") as m_run:
            m_run.return_value = _CompletedProcess(1, "", "no such file")
            with pytest.raises(VideoValidationError):
                _run_ffprobe("测试.mp4")

    def test_ascii_filename_still_works(self) -> None:
        """回归：纯英文文件名解析不受影响"""
        with mock.patch.object(core_utils.subprocess, "run") as m_run:
            m_run.return_value = _CompletedProcess(0, _fake_probe("plain.mp4"))
            probe = _run_ffprobe("plain.mp4")
        assert probe["format"]["filename"] == "plain.mp4"


# ── 根因演示：cp936 解码 UTF-8 输出会失败 ────────────────────


class TestRootCauseDemonstration:
    """文档化根因：ffprobe 的 UTF-8 输出无法用 cp936 解码"""

    def test_cp936_decode_of_utf8_ffprobe_output_fails(self) -> None:
        """证明修复前的 bug：UTF-8 字节用 cp936 解码会抛 UnicodeDecodeError"""
        utf8_bytes = _fake_probe("测试视频.mp4").encode("utf-8")
        with pytest.raises(UnicodeDecodeError):
            utf8_bytes.decode("cp936")

    def test_utf8_decode_of_utf8_ffprobe_output_succeeds(self) -> None:
        """修复后：UTF-8 字节用 utf-8 解码成功，JSON 可解析"""
        utf8_bytes = _fake_probe("测试视频.mp4").encode("utf-8")
        data = json.loads(utf8_bytes.decode("utf-8"))
        assert data["format"]["filename"] == "测试视频.mp4"


# ── validate_video_file / validate_output_video ─────────────


class TestValidateVideoNonAscii:
    """验证 validate_video_file / validate_output_video 对非英文文件名不抛异常"""

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_validate_video_file_non_ascii_name(self, name: str, tmp_path) -> None:
        """mock _run_ffprobe 返回有效探测结果，非英文文件名验证通过"""
        # 创建真实临时文件以满足 os.path.exists / getsize 检查
        video = tmp_path / name
        video.write_bytes(b"\x00" * 1024)
        probe = json.loads(_fake_probe(str(video)))
        with mock.patch.object(core_utils, "_run_ffprobe", return_value=probe):
            info = validate_video_file(str(video))
        assert info["width"] == 160
        assert info["height"] == 120
        assert info["duration"] == 1.0
        assert info["file_path"] == str(video)

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_validate_output_video_non_ascii_name(self, name: str, tmp_path) -> None:
        """非英文文件名的输出视频验证通过"""
        video = tmp_path / name
        video.write_bytes(b"\x00" * 1024)
        probe = json.loads(_fake_probe(str(video)))
        with mock.patch.object(core_utils, "_run_ffprobe", return_value=probe):
            assert validate_output_video(str(video)) is True

    def test_validate_video_file_ascii_name_regression(self, tmp_path) -> None:
        """回归：纯英文文件名验证逻辑不受影响"""
        video = tmp_path / "plain.mp4"
        video.write_bytes(b"\x00" * 1024)
        probe = json.loads(_fake_probe(str(video)))
        with mock.patch.object(core_utils, "_run_ffprobe", return_value=probe):
            info = validate_video_file(str(video))
        assert info["width"] == 160 and info["height"] == 120


# ── 真实 ffprobe 集成测试（需 ffmpeg/ffprobe） ───────────────


def _ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg/ffprobe 不可用")
class TestRealFfprobeIntegration:
    """用真实 ffmpeg 生成非英文文件名视频，端到端验证 _run_ffprobe 与 validate"""

    @staticmethod
    def _make_video(path: str) -> None:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "testsrc=duration=1:size=160x120:rate=15",
             "-pix_fmt", "yuv420p", path, "-loglevel", "error"],
            check=True,
        )

    @pytest.mark.parametrize("name", [
        pytest.param("测试视频.mp4", id="chinese"),
        pytest.param("動画01.mp4", id="japanese"),
        pytest.param("视频_動画.mp4", id="mixed"),
    ])
    def test_run_ffprobe_real_non_ascii(self, name: str, tmp_path) -> None:
        """真实 ffprobe 解析非英文文件名视频，返回有效探测字典"""
        video = str(tmp_path / name)
        self._make_video(video)
        probe = _run_ffprobe(video)
        assert probe["format"]["filename"] == video
        assert probe["streams"][0]["codec_type"] == "video"
        assert int(probe["streams"][0]["width"]) == 160

    @pytest.mark.parametrize("name", [
        pytest.param("测试视频.mp4", id="chinese"),
        pytest.param("動画01.mp4", id="japanese"),
    ])
    def test_validate_video_file_real_non_ascii(self, name: str, tmp_path) -> None:
        """validate_video_file 对真实非英文文件名视频返回正确元数据"""
        video = str(tmp_path / name)
        self._make_video(video)
        info = validate_video_file(video)
        assert info["width"] == 160
        assert info["height"] == 120
        assert info["duration"] == pytest.approx(1.0, abs=0.1)
        assert info["file_path"] == video

    def test_validate_output_video_real_non_ascii(self, tmp_path) -> None:
        """validate_output_video 对真实非英文文件名视频通过"""
        video = str(tmp_path / "输出结果.mp4")
        self._make_video(video)
        assert validate_output_video(video) is True


# ── 路径构造保留 Unicode（流水线各环节） ─────────────────────


class TestUnicodePathConstruction:
    """验证由非英文视频名派生的中间/输出路径正确保留 Unicode 字符"""

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_get_output_dir_preserves_video_name(self, name: str) -> None:
        """ConfigManager.get_output_dir(video_name) 保留非英文视频名"""
        mgr = ConfigManager(PROJECT_ROOT)
        out = mgr.get_output_dir(name)
        assert name in out

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_prepare_output_path_preserves_basename(self, name: str, tmp_path) -> None:
        """prepare_output_path 构造的输出文件名保留非英文 basename"""
        basename = os.path.splitext(name)[0]
        config = {"output_dir": str(tmp_path)}
        out_dir, out_path = prepare_output_path(basename, config)
        assert basename in out_path
        assert out_path.endswith(f"output_{basename}.mp4")
        assert os.path.isdir(out_dir)

    def test_prepare_output_path_default_dir_unicode(self) -> None:
        """未注入 output_dir 时回退到 PROJECT_ROOT/output/<basename>，保留 Unicode"""
        basename = "测试视频"
        out_dir, out_path = prepare_output_path(basename, {})
        assert basename in out_dir
        assert out_path.endswith("output_测试视频.mp4")


# ── JSON / 文本读写 Unicode 往返 ────────────────────────────


class TestUnicodeFileIO:
    """验证中间文件（copilot JSON / formation / actions / track_result）的
    中文内容读写往返一致——这些文件名本身也可能含非英文字符"""

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_json_unicode_roundtrip(self, name: str, tmp_path) -> None:
        """非英文文件名的 JSON 文件读写往返一致，内容不被转义为 \\uXXXX"""
        path = str(tmp_path / f"maa_copilot_{name}.json")
        data = {"stage_name": "测试关卡", "doc": {"title": "動画認識"},
                "opers": [{"name": "米格鲁"}]}
        write_json_file(path, data)
        # 文件内容应为 UTF-8 且中文原样存储（非 ASCII 转义）
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        assert "测试关卡" in raw
        assert read_json_file(path) == data

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_text_unicode_roundtrip(self, name: str, tmp_path) -> None:
        """非英文文件名的文本文件（formation/actions）读写往返一致"""
        path = str(tmp_path / f"formation_{name}.txt")
        content = "1.米格鲁 2.遥 3.黒角\n部署干员"
        write_text_file(path, content)
        with open(path, "r", encoding="utf-8") as f:
            assert f.read() == content


# ── 跨平台文件名编码方案：Python 原生 Unicode 路径 ──────────


class TestCrossPlatformPathHandling:
    """验证 Python 原生路径 API 正确处理非英文文件名（存储/传输环节）

    Python 3 的 os.path / open / os.makedirs 在 Windows 上使用宽字符 API，
    天然支持 Unicode 路径；JSON 用 ensure_ascii=False 写 UTF-8。这些环节
    无需额外处理，本测试固化该不变量。
    """

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_makedirs_and_open_non_ascii(self, name: str, tmp_path) -> None:
        """非英文目录创建与文件写入读取成功"""
        sub = tmp_path / name / "subdir"
        os.makedirs(str(sub), exist_ok=True)
        assert os.path.isdir(str(sub))
        fpath = sub / f"output_{name}.mp4"
        fpath.write_bytes(b"\x00\x01\x02")
        assert os.path.getsize(str(fpath)) == 3

    @pytest.mark.parametrize("name", NON_ASCII_NAMES)
    def test_basename_splitext_preserves_unicode(self, name: str) -> None:
        """os.path.basename/splitext 对非英文文件名正确拆分"""
        base = os.path.basename(name)
        stem, ext = os.path.splitext(base)
        assert ext == ".mp4"
        assert stem == name[:-4]
