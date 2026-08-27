"""战场收集阶段过滤非可部署格（自动召唤物误判修复）的单元测试。

背景：干员技能会把召唤物自动部署到非可部署格上（如圣聆初雪二技能在
蓝门 ``tile_end`` 处部署的"冻结的蓝门"），该召唤物无法手动部署/撤退，
却带与干员一致的头像框与血条，会被 YOLO 检出并映射到蓝门格，进而产生
假 Deploy/Retreat 并污染格子↔干员映射。

被测逻辑：``BattleAnalyzer._buildable_tiles``（白名单提取）与
``_detect_battlefield_voted``（战场集合收集过滤）。

测试用最小 fake level + 手工投影坐标网格 + stub detector/classifier，
不加载 ONNX 模型与 OCR。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from arknights_video_recognition.battle.analyzer import BattleAnalyzer
from arknights_video_recognition.battle.detector import Detection

# --- 测试几何 ---------------------------------------------------------------
#
# 手工构造 3x4 投影坐标网格（无需真实地图数据）：
# - A = (row=1, col=1) @ (200, 300)：可部署格（模拟普通地面格）
# - B = (row=1, col=2) @ (260, 330)：非可部署格（模拟蓝门 tile_end）
#
# YOLO 框经 det_box_move=[0,-50,60,60] 偏移为 60x60 rect 后做包含测试：
# - boxA = [170, 320, 60, 50] → rect x∈[170,230] y∈[270,330]，仅含 A
# - boxB = [230, 350, 60, 50] → rect x∈[230,290] y∈[300,360]，仅含 B
POSITIONS = [
    [(100, 100), (160, 120), (220, 140), (280, 160)],
    [(140, 240), (200, 300), (260, 330), (320, 380)],
    [(180, 400), (240, 430), (300, 460), (360, 490)],
]
TILE_A = (1, 1)
TILE_B = (1, 2)
BOX_A = [170, 320, 60, 50]
BOX_B = [230, 350, 60, 50]
SCREEN_SIZE = (1280, 720)


def _tile(buildable: int, key: str = "tile_road") -> dict:
    return {"heightType": 0, "buildableType": buildable, "tileKey": key}


def _level(door_buildable=None, omit_field=False):
    """构造测试关卡：B 为蓝门格（buildableType==0），其余可部署。

    omit_field=True 时全部 tile 不带 buildableType 字段（fail-open 回归用）；
    door_buildable 非 None 时覆盖蓝门格的 buildableType。
    """
    grid = []
    for row in range(3):
        grid_row = []
        for col in range(4):
            if (row, col) == TILE_B:
                bt = 0 if door_buildable is None else door_buildable
                tile = _tile(bt, "tile_end") if not omit_field else {"heightType": 0}
            else:
                tile = (
                    _tile(1)
                    if not omit_field
                    else {"heightType": 0}
                )
            grid_row.append(tile)
        grid.append(grid_row)
    return {
        "stageId": "main_00-01",
        "code": "0-1",
        "width": 4,
        "height": 3,
        "tiles": grid,
    }


class StubDetector:
    """恒返回预设检测框的 stub detector。"""

    def __init__(self, boxes):
        self._boxes = [list(b) for b in boxes]

    def detect(self, frame):
        return [Detection(box=list(b), score=0.9, class_id=0) for b in self._boxes]


class StubClassifier:
    """方向分类恒返回 Right（raw 第一维最大）；技能状态恒 n。"""

    def classify_deploy_direction(self, patch):
        return "Right", np.array([9.0, 1.0, 1.0, 1.0], dtype=np.float32)

    def classify_skill_ready(self, patch):
        return "n"


def _make_frame():
    return np.full((720, 1280, 3), 30, dtype=np.uint8)


def _clip():
    """构造带 key_frame 的伪 clip：video_frames=None 时走单帧回退路径。"""
    return SimpleNamespace(
        start_time=2.0,
        end_time=2.0,
        key_frame=_make_frame(),
        deployment=[],
        ends_oper_name="",
    )


@pytest.fixture()
def analyzer():
    # ocr_engine 传哨兵对象避免触发真实 OCR 引擎加载；这些路径不使用 ocr
    return BattleAnalyzer(ocr_engine=object())


# --- _buildable_tiles 单元 ---------------------------------------------------


class TestBuildableTiles:
    def test_normal_level(self):
        buildable = BattleAnalyzer._buildable_tiles(_level())
        assert buildable is not None
        assert TILE_A in buildable
        assert TILE_B not in buildable  # 蓝门格 buildableType==0 被排除

    def test_missing_tiles_returns_none(self):
        assert BattleAnalyzer._buildable_tiles({}) is None
        assert BattleAnalyzer._buildable_tiles(None) is None
        assert BattleAnalyzer._buildable_tiles({"tiles": []}) is None

    def test_missing_field_failopen_per_tile(self):
        # 个别 tile 缺 buildableType 字段时按可部署处理（不整级放弃）
        level = _level(omit_field=True)
        buildable = BattleAnalyzer._buildable_tiles(level)
        assert buildable == {(r, c) for r in range(3) for c in range(4)}

    def test_malformed_rows_returns_none(self):
        assert BattleAnalyzer._buildable_tiles({"tiles": ["bad"]}) is None
        assert BattleAnalyzer._buildable_tiles({"tiles": [[1, 2]]}) is None


# --- 战场收集过滤 ------------------------------------------------------------


class TestDetectBattlefieldFilter:
    def test_summon_on_blue_door_filtered_out(self, analyzer):
        """蓝门格上的召唤物检测被丢弃：不进入战场集合、不产生假 Deploy。

        修复前行为：B 进入 mode_tiles 成为 newcomer，deploy 分支因 deployed
        为空而回退 ends_oper_name（此处为真实干员名"圣聆初雪"），产出
        location=蓝门的假 Deploy 并污染 operator_locations。
        """
        detector = StubDetector([BOX_A, BOX_B])
        clip = _clip()
        bf = analyzer._detect_battlefield_voted(
            clip, None, None, detector, StubClassifier(),
            _level(), SCREEN_SIZE, POSITIONS,
        )
        assert set(bf.keys()) == {TILE_A}

        pre_valid = SimpleNamespace(
            deployment=[],
            battlefield={TILE_A: SimpleNamespace(direction="Right", new_here=False)},
            ends_oper_name="圣聆初雪",
        )
        actions = analyzer._process_changes(bf, [], pre_valid, clip)
        assert actions == []
        assert TILE_B not in analyzer.location_operators
        assert "圣聆初雪" not in analyzer.operator_locations

    def test_field_unchanged_no_spurious_actions(self, analyzer):
        """场上无变化（前后两片段同一组检测）时不产生任何动作。

        防止过滤本身造成集合缩水型假 Retreat：prev_bf 与 cur bf 均来自
        同一过滤管线，蓝门格从未进入任何一侧。
        """
        detector = StubDetector([BOX_A])
        pre_clip = _clip()
        cur_clip = _clip()
        pre_bf = analyzer._detect_battlefield_voted(
            pre_clip, None, None, detector, StubClassifier(),
            _level(), SCREEN_SIZE, POSITIONS,
        )
        cur_bf = analyzer._detect_battlefield_voted(
            cur_clip, None, None, detector, StubClassifier(),
            _level(), SCREEN_SIZE, POSITIONS,
        )
        pre_valid = SimpleNamespace(deployment=[], battlefield=pre_bf,
                                    ends_oper_name="")
        actions = analyzer._process_changes(cur_bf, [], pre_valid, cur_clip)
        assert actions == []

    def test_operator_on_buildable_neighbor_still_detected(self, analyzer):
        """相邻可部署格上的真实干员不受白名单影响：正常 newcomer + Deploy。

        传入空战场 pre_valid（而非 None）以触发 newcomer 标记与方向分类
        （对齐生产语义：首个片段不做方向分类）。pre_valid.deployment 提供
        真实消失槽位（该干员），使 deployed 含有效名 → 产出带真名的 Deploy
        （修复自动召唤物误判后，无名字不再退回 Unknown_EndsEmpty）。
        """
        detector = StubDetector([BOX_A])
        clip = _clip()
        pre_valid_detect = SimpleNamespace(
            deployment=[{"name": "能天使", "role": "Sniper"}],
            battlefield={}, ends_oper_name="",
        )
        bf = analyzer._detect_battlefield_voted(
            clip, pre_valid_detect, None, detector, StubClassifier(),
            _level(), SCREEN_SIZE, POSITIONS,
        )
        assert set(bf.keys()) == {TILE_A}
        state = bf[TILE_A]
        assert getattr(state, "new_here", False) is True
        assert getattr(state, "direction", "") == "Right"

        actions = analyzer._process_changes(bf, [], pre_valid_detect, clip)
        assert len(actions) == 1
        act = actions[0]
        assert act.type == "Deploy"
        assert act.name == "能天使"
        # location 输出为 [col, row]
        assert act.location == [TILE_A[1], TILE_A[0]]
        assert act.direction == "Right"
        assert analyzer.location_operators[TILE_A] == act.name

    def test_all_forbidden_level_clears_everything(self, analyzer):
        """极端情形：整张图都不可部署时所有检测被丢弃，战场集合为空。"""
        level = _level()
        level["tiles"] = [
            [_tile(0, "tile_forbidden") for _ in range(4)] for _ in range(3)
        ]
        detector = StubDetector([BOX_A, BOX_B])
        bf = analyzer._detect_battlefield_voted(
            _clip(), None, None, detector, StubClassifier(),
            level, SCREEN_SIZE, POSITIONS,
        )
        assert bf == {}

    def test_failopen_without_buildable_field_keeps_old_behavior(self, analyzer):
        """tile 缺 buildableType 字段时 fail-open：不过滤，保持旧行为。"""
        detector = StubDetector([BOX_B])
        bf = analyzer._detect_battlefield_voted(
            _clip(), None, None, detector, StubClassifier(),
            _level(omit_field=True), SCREEN_SIZE, POSITIONS,
        )
        # 蓝门格检测照常进入战场集合（与修复前一致）
        assert TILE_B in bf
