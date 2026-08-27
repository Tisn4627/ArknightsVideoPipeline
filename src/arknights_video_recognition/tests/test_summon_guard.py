"""自动召唤物（不占部署栏，如维什戴尔的召唤物）误判为手动部署的防护单元测试。

背景：手动部署必然伴随部署栏槽位减少；而白名单干员（``_AUTO_SUMMON_OPERATORS``
= 维什戴尔）的召唤物在部署/开技能时**自动部署在可部署格**上，不占部署栏
（出现与撤退均不改变部署栏）、仅增加场上新生格子。旧逻辑把新增格逐个配
deployed 名，耗完后用 ``ends_oper_name`` / ``"Unknown_EndsEmpty"`` 兜底，
导致召唤物格拿到干员名产出假 Deploy（位置错误）并污染格子↔干员映射。

被测逻辑：
- ``_process_changes`` 召唤物守卫（仅白名单干员部署/在场且 M > N 时生效：
  数量守卫 + 头像仲裁 + Retreat 空名拦截）；
- ``_pair_newcomers`` / ``_score_tile_name_pairs`` 配对；
- **其他干员保留 Maa 兜底配对**（ends_oper_name → Unknown_EndsEmpty）。

纯逻辑测试，不加载 ONNX/OCR，头像用 numpy 数组模拟（同一干员头像相同数组、
不同单位用不同随机数组，使 TM_CCOEFF_NORMED 分数可区分）。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from arknights_video_recognition.battle.analyzer import (
    BattleAnalyzer,
    _OperState,
)

# 手头测试几何沿用最小 fake level 的坐标（同 test_battlefield_tile_filter）：
# 只需在可部署格上排布单位，不加载真实地图。
SUM_TILE = (1, 1)   # 真干员格 A
SUM_TILE2 = (1, 2)  # 召唤物格 B


def _oper(tile, direction="Right", new_here=True, avatar=None):
    """构造一个 _OperState。"""
    return _OperState(
        name="Unknown", tile=tile, direction=direction,
        skill_ready="n", box=[0, 0, 0, 0], avatar=avatar,
        new_here=new_here,
    )


def _avatars():
    """生成两套可区分的头像：ops（干员）与 summon（召唤物）。"""
    rng = np.random.default_rng(7)
    oper = rng.integers(0, 255, (12, 12, 3), dtype=np.uint8)
    summon = rng.integers(0, 255, (12, 12, 3), dtype=np.uint8)
    return oper, summon


@pytest.fixture()
def analyzer():
    # ocr_engine 传哨兵对象避免触发真实 OCR 引擎加载
    return BattleAnalyzer(ocr_engine=object())


# --- _pair_newcomers：数量守恒 ------------------------------------------------


class TestPairingCountGuard:
    def test_pure_summon_no_deployed_returns_empty(self, analyzer):
        """deployed 为空但 new_tiles 非空（纯召唤物 clip）→ 全部跳过。"""
        oper, summon = _avatars()
        battlefield = {
            SUM_TILE: _oper(SUM_TILE, avatar=oper),
            SUM_TILE2: _oper(SUM_TILE2, avatar=summon),
        }
        pairs = analyzer._pair_newcomers([SUM_TILE, SUM_TILE2], [], battlefield)
        assert pairs == []

    def test_m_equals_n_full_pairing(self, analyzer):
        """M == N：无召唤物，按坐标序全配对，零丢弃。"""
        battlefield = {
            SUM_TILE: _oper(SUM_TILE),
            SUM_TILE2: _oper(SUM_TILE2),
        }
        pairs = analyzer._pair_newcomers(
            [SUM_TILE, SUM_TILE2], ["干员A", "干员B"], battlefield,
        )
        # 坐标序：SUM_TILE < SUM_TILE2 → 干员A 配第一格
        assert pairs == [(SUM_TILE, "干员A"), (SUM_TILE2, "干员B")]


class TestPairingAvatarArbitration:
    def test_matches_operator_tile(self, analyzer):
        """M > N：头像仲裁应把真干员名配给头像最匹配的格子（真干员格）。"""
        oper, summon = _avatars()
        analyzer.all_avatars["维什戴尔"] = oper
        battlefield = {
            # 真干员格头像 == 部署栏头像 → 高匹配
            SUM_TILE: _oper(SUM_TILE, avatar=oper),
            # 召唤物格头像 != 部署栏头像 → 低匹配
            SUM_TILE2: _oper(SUM_TILE2, avatar=summon),
        }
        pairs = analyzer._pair_newcomers(
            [SUM_TILE, SUM_TILE2], ["维什戴尔"], battlefield,
        )
        assert pairs == [(SUM_TILE, "维什戴尔")]
        # 召唤物格不进配对 → 不产 Deploy、不入映射
        assert not any(t == SUM_TILE2 for t, _ in pairs)

    def test_fallback_to_sorted_when_no_avatar(self, analyzer):
        """头像缺失（avatar=None）→ 回退坐标序取前 N，仍无名字兜底。"""
        battlefield = {
            SUM_TILE: _oper(SUM_TILE, avatar=None),
            SUM_TILE2: _oper(SUM_TILE2, avatar=None),
        }
        pairs = analyzer._pair_newcomers(
            [SUM_TILE, SUM_TILE2], ["维什戴尔"], battlefield,
        )
        # 坐标序第一格 SUM_TILE 拿真名，召唤物格 SUM_TILE2 跳过
        assert pairs == [(SUM_TILE, "维什戴尔")]

    def test_fallback_when_all_avatars_empty(self, analyzer):
        """all_avatars 为空（头像仲裁无数据源）→ 回退坐标序。"""
        battlefield = {
            SUM_TILE: _oper(SUM_TILE),
            SUM_TILE2: _oper(SUM_TILE2),
        }
        pairs = analyzer._pair_newcomers(
            [SUM_TILE, SUM_TILE2], ["维什戴尔"], battlefield,
        )
        assert pairs == [(SUM_TILE, "维什戴尔")]

    def test_pairing_deterministic(self, analyzer):
        """不同 battlefield 插入序产出相同配对（排序决定，非哈希序）。"""
        oper, summon = _avatars()
        analyzer.all_avatars["维什戴尔"] = oper
        bf1 = {
            SUM_TILE: _oper(SUM_TILE, avatar=oper),
            SUM_TILE2: _oper(SUM_TILE2, avatar=summon),
        }
        bf2 = {
            SUM_TILE2: _oper(SUM_TILE2, avatar=summon),
            SUM_TILE: _oper(SUM_TILE, avatar=oper),
        }
        p1 = analyzer._pair_newcomers([SUM_TILE, SUM_TILE2], ["维什戴尔"], bf1)
        p2 = analyzer._pair_newcomers([SUM_TILE, SUM_TILE2], ["维什戴尔"], bf2)
        assert p1 == p2


# --- _process_changes：Deploy/Retreat 集成 -----------------------------------


class TestProcessChangesGuard:
    def test_deploy_with_auto_summon_single_action(self, analyzer):
        """场景 A：部署本体 + 召唤物（M=2,N=1）→ 恰 1 条真 Deploy，无占位名。"""
        oper, summon = _avatars()
        analyzer.all_avatars["维什戴尔"] = oper
        battlefield = {
            SUM_TILE: _oper(SUM_TILE, direction="Right", avatar=oper),
            SUM_TILE2: _oper(SUM_TILE2, avatar=summon),
        }
        clip = SimpleNamespace(start_time=10.0)
        pre_valid = SimpleNamespace(
            battlefield={},
            deployment=[{"name": "维什戴尔", "role": "Sniper"}],
            ends_oper_name="陈",
        )
        actions = analyzer._process_changes(
            battlefield, [], pre_valid, clip,
        )
        # 恰 1 条 Deploy，名字是本体（非兜底的 ends_oper_name "陈"，也非占位名）
        deploys = [a for a in actions if a.type == "Deploy"]
        assert len(deploys) == 1
        assert deploys[0].name == "维什戴尔"
        assert deploys[0].location == [SUM_TILE[1], SUM_TILE[0]]
        # 召唤物格不入映射，真干员格入映射
        assert SUM_TILE2 not in analyzer.location_operators
        assert analyzer.operator_locations.get("维什戴尔") == SUM_TILE

    def test_retreat_with_summons_single_action(self, analyzer):
        """场景 C：本体+召唤物同时消失（召唤物到期/被击破自动消失）
        → 仅退真干员，召唤物格无映射名被跳过。

        召唤物出现与撤退均不改变部署栏，无从也无需识别为玩家操作。
        """
        # 场上：A 真干员（入映射）、B 召唤物（从未入映射）
        analyzer.operator_locations["维什戴尔"] = SUM_TILE
        analyzer.location_operators[SUM_TILE] = "维什戴尔"
        battlefield = {}  # 当前战场全空
        clip = SimpleNamespace(start_time=20.0)
        pre_valid = SimpleNamespace(
            battlefield={
                SUM_TILE: _oper(SUM_TILE, new_here=False),
                SUM_TILE2: _oper(SUM_TILE2, new_here=False),
            },
            deployment=[],
            ends_oper_name="",
        )
        actions = analyzer._process_changes(
            battlefield, [], pre_valid, clip,
        )
        retreats = [a for a in actions if a.type == "Retreat"]
        # 仅 1 条真 Retreat（召唤物 B 自动消失，不产出假撤退）
        assert len(retreats) == 1
        assert retreats[0].name == "维什戴尔"
        assert retreats[0].location == [SUM_TILE[1], SUM_TILE[0]]

    def test_summon_auto_expire_no_action(self, analyzer):
        """场景 E：仅召唤物消失（本体留存，部署栏不变）→ 跳过，无动作。"""
        battlefield = {}  # 召唤物消失，场上无对应格
        clip = SimpleNamespace(start_time=23.0)
        pre_valid = SimpleNamespace(
            battlefield={SUM_TILE2: _oper(SUM_TILE2, new_here=False)},
            deployment=[],
            ends_oper_name="",
        )
        actions = analyzer._process_changes(
            battlefield, [], pre_valid, clip,
        )
        assert actions == []

    def test_skill_summons_then_deploy_arbitrated(self, analyzer):
        """场景 B：维什戴尔在场开三技能召唤 2 物，随后部署能天使
        → 数量守卫 + 仲裁使真干员格拿真名，召唤物格跳过。"""
        oper, summon = _avatars()
        analyzer.all_avatars["能天使"] = oper
        # 守卫条件：维什戴尔已在场上（其技能召唤物可在任意后续 clip 浮现）
        analyzer.operator_locations["维什戴尔"] = (0, 0)
        analyzer.location_operators[(0, 0)] = "维什戴尔"
        # 场上 3 个 newcomer：能天使格(高匹配) + 两个召唤物格(低匹配)
        battlefield = {
            SUM_TILE: _oper(SUM_TILE, avatar=oper),
            SUM_TILE2: _oper(SUM_TILE2, avatar=summon),
            (2, 1): _oper((2, 1), avatar=summon),
        }
        clip = SimpleNamespace(start_time=30.0)
        pre_valid = SimpleNamespace(
            battlefield={(0, 0): _oper((0, 0), new_here=False)},
            deployment=[{"name": "能天使", "role": "Sniper"}],
            ends_oper_name="",
        )
        actions = analyzer._process_changes(
            battlefield, [], pre_valid, clip,
        )
        deploys = [a for a in actions if a.type == "Deploy"]
        assert len(deploys) == 1
        assert deploys[0].name == "能天使"
        assert deploys[0].location == [SUM_TILE[1], SUM_TILE[0]]
        # 两个召唤物格均不入映射
        assert SUM_TILE2 not in analyzer.location_operators
        assert (2, 1) not in analyzer.location_operators
        # 本体映射不受影响
        assert analyzer.operator_locations.get("维什戴尔") == (0, 0)


# --- 守卫范围：其他干员保留 Maa 兜底 -----------------------------------------


class TestGuardScope:
    def test_other_operator_m_over_n_keeps_maa_fallback(self, analyzer):
        """其他干员 M > N（无白名单干员部署/在场）：保留 Maa 兜底配对。

        ends_oper_name 兜底不丢动作——M > N 对非白名单干员属检测异常，
        真实部署不能被数量守卫误丢。
        """
        battlefield = {
            SUM_TILE: _oper(SUM_TILE),
            SUM_TILE2: _oper(SUM_TILE2),
        }
        clip = SimpleNamespace(start_time=31.0)
        pre_valid = SimpleNamespace(
            battlefield={},
            deployment=[{"name": "能天使", "role": "Sniper"}],
            ends_oper_name="陈",
        )
        actions = analyzer._process_changes(
            battlefield, [], pre_valid, clip,
        )
        deploys = [a for a in actions if a.type == "Deploy"]
        assert len(deploys) == 2
        # 坐标序：第一格拿 deployed 名，第二格拿 ends_oper_name 兜底
        assert deploys[0].name == "能天使"
        assert deploys[0].location == [SUM_TILE[1], SUM_TILE[0]]
        assert deploys[1].name == "陈"
        # 兜底配对照常写入映射（Maa 行为）
        assert analyzer.location_operators[SUM_TILE] == "能天使"
        assert analyzer.location_operators[SUM_TILE2] == "陈"

    def test_other_operator_exhausted_fallback_unknown_ends_empty(self, analyzer):
        """其他干员 M > N 且 ends_oper_name 为空 → Unknown_EndsEmpty 保留。

        占位名动作由转换层（pipeline._convert_actions）过滤，识别层保留
        Maa 兜底语义不丢动作。
        """
        battlefield = {
            SUM_TILE: _oper(SUM_TILE),
            SUM_TILE2: _oper(SUM_TILE2),
        }
        clip = SimpleNamespace(start_time=32.0)
        pre_valid = SimpleNamespace(
            battlefield={},
            deployment=[{"name": "能天使", "role": "Sniper"}],
            ends_oper_name="",
        )
        actions = analyzer._process_changes(
            battlefield, [], pre_valid, clip,
        )
        deploys = [a for a in actions if a.type == "Deploy"]
        assert len(deploys) == 2
        assert deploys[0].name == "能天使"
        assert deploys[1].name == "Unknown_EndsEmpty"

    def test_wisadel_on_field_m_equals_n_normal_pairing(self, analyzer):
        """白名单干员在场但 M == N（本批无召唤物浮现）→ 正常全配对。

        守卫只在 M > N 时改变行为，不影响正常部署。
        """
        analyzer.operator_locations["维什戴尔"] = (0, 0)
        analyzer.location_operators[(0, 0)] = "维什戴尔"
        battlefield = {
            SUM_TILE: _oper(SUM_TILE),
            SUM_TILE2: _oper(SUM_TILE2),
        }
        clip = SimpleNamespace(start_time=33.0)
        pre_valid = SimpleNamespace(
            battlefield={(0, 0): _oper((0, 0), new_here=False)},
            deployment=[
                {"name": "能天使", "role": "Sniper"},
                {"name": "陈", "role": "Pioneer"},
            ],
            ends_oper_name="",
        )
        actions = analyzer._process_changes(
            battlefield, [], pre_valid, clip,
        )
        deploys = [a for a in actions if a.type == "Deploy"]
        assert len(deploys) == 2
        assert {d.name for d in deploys} == {"能天使", "陈"}