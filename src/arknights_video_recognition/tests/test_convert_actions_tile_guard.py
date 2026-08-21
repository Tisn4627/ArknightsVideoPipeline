"""转换层落点校验（Deploy/Retreat 防御过滤）的单元测试。

背景：检测端已按格子白名单过滤战场集合，但为拦截仍可能携带非可部署
落点的动作（如技能自动召唤物被误判为干员），``_convert_actions`` 对
Deploy/Retreat 的 location 再做一次 ``buildableType`` 校验并丢弃非法
动作。Skill 不校验（其 location 仅作参考定位）。

被测逻辑：模块级 :func:`_is_location_buildable` 与
``VideoRecognitionPipeline._convert_actions``。
"""

import pytest

from arknights_video_recognition.battle.analyzer import Action as BattleAction
from arknights_video_recognition.copilot import ActionType
from arknights_video_recognition.pipeline import (
    VideoRecognitionPipeline,
    _is_location_buildable,
)

# (row=1, col=1) 为蓝门格（buildableType==0），其余可部署
LEVEL = {
    "stageId": "main_00-01",
    "tiles": [
        [{"buildableType": 1}, {"buildableType": 1}],
        [{"buildableType": 1}, {"buildableType": 0, "tileKey": "tile_end"}],
    ],
}


@pytest.fixture()
def pipeline():
    """绕过 __init__ 构造轻量实例。

    _convert_actions 只使用模块级常量与参数，不触碰实例状态，无需加载
    ONNX 模型 / OCR 引擎等重型资源。
    """
    return VideoRecognitionPipeline.__new__(VideoRecognitionPipeline)


def _deploy(location, name="圣聆初雪"):
    return BattleAction(type="Deploy", name=name, location=list(location),
                        direction="Right", ts=1.0)


def _retreat(location):
    return BattleAction(type="Retreat", name="圣聆初雪",
                        location=list(location), ts=2.0)


def _skill(location):
    return BattleAction(type="Skill", name="圣聆初雪",
                        location=list(location), ts=3.0)


# --- _is_location_buildable 单元 ---------------------------------------------


class TestIsLocationBuildable:
    def test_forbidden_tile_rejected(self):
        # location=[col, row]=[1, 1] → tiles[1][1] 蓝门格
        assert _is_location_buildable(LEVEL, [1, 1]) is False

    def test_buildable_tile_accepted(self):
        assert _is_location_buildable(LEVEL, [1, 0]) is True
        assert _is_location_buildable(LEVEL, [0, 0]) is True

    def test_failopen_on_missing_level(self):
        assert _is_location_buildable(None, [1, 1]) is True
        assert _is_location_buildable({}, [1, 1]) is True

    def test_failopen_on_bad_location(self):
        assert _is_location_buildable(LEVEL, None) is True
        assert _is_location_buildable(LEVEL, [1]) is True

    def test_failopen_on_out_of_bounds(self):
        assert _is_location_buildable(LEVEL, [9, 9]) is True
        assert _is_location_buildable(LEVEL, [-1, -1]) is True

    def test_failopen_on_missing_field(self):
        level = {"tiles": [[{"heightType": 0}]]}
        assert _is_location_buildable(level, [0, 0]) is True


# --- _convert_actions 集成 ----------------------------------------------------


class TestConvertActionsGuard:
    def test_deploy_on_non_buildable_dropped(self, pipeline, capsys):
        actions = pipeline._convert_actions([_deploy([1, 1])], level=LEVEL)
        assert actions == []
        err = capsys.readouterr().err
        assert "非可部署格" in err
        assert "圣聆初雪" in err

    def test_deploy_on_buildable_kept(self, pipeline):
        actions = pipeline._convert_actions([_deploy([0, 0])], level=LEVEL)
        assert len(actions) == 1
        act = actions[0]
        assert act.type == ActionType.DEPLOY
        assert act.name == "圣聆初雪"
        assert act.location == [0, 0]
        assert act.direction == "Right"

    def test_retreat_on_non_buildable_dropped(self, pipeline, capsys):
        actions = pipeline._convert_actions([_retreat([1, 1])], level=LEVEL)
        assert actions == []
        assert "Retreat" in capsys.readouterr().err

    def test_retreat_on_buildable_kept(self, pipeline):
        actions = pipeline._convert_actions([_retreat([1, 0])], level=LEVEL)
        assert len(actions) == 1
        assert actions[0].type == ActionType.RETREAT
        assert actions[0].location == [1, 0]

    def test_skill_not_checked(self, pipeline):
        """按约定 Skill 不做落点校验：蓝门格上的 Skill 原样保留。"""
        actions = pipeline._convert_actions([_skill([1, 1])], level=LEVEL)
        assert len(actions) == 1
        assert actions[0].type == ActionType.SKILL
        assert actions[0].location == [1, 1]

    def test_level_none_keeps_everything(self, pipeline):
        """level 未提供时跳过校验（fail-open），不丢弃任何动作。"""
        actions = pipeline._convert_actions(
            [_deploy([1, 1]), _retreat([1, 1]), _skill([1, 1])], level=None
        )
        assert len(actions) == 3

    def test_malformed_level_keeps_everything(self, pipeline):
        for bad_level in ({}, {"tiles": "bad"}, {"tiles": [["x"]]}):
            actions = pipeline._convert_actions(
                [_deploy([1, 1])], level=bad_level
            )
            assert len(actions) == 1

    def test_placeholder_filter_still_applies_first(self, pipeline):
        """占位名 Deploy 的既有过滤不受影响（无 location 时也不校验落点）。"""
        phantom = BattleAction(type="Deploy", name="UnknownDeployment",
                               location=None, direction="None", ts=4.0)
        actions = pipeline._convert_actions([phantom], level=None)
        assert actions == []
