"""제스처 판별 자동 테스트 — 웹캠 없이 가짜 관절 좌표로 확인합니다.

실행: python -m unittest -v
"""
import unittest

from gesture_control.common import Command, EventType, Hand
from gesture_control.gestures import GestureRecognizer, Pose, classify_pose

FPS = 30
DT = 1 / FPS
PALM = 80.0  # 손바닥 크기(픽셀)


def make_hand(pose: str, cx: float = 320, cy: float = 240, label: str = "Right", s: float = PALM) -> Hand:
    """손바닥 중심 근처가 (cx, cy)인 가짜 손. pose: open / fist / v / point"""
    extended = {
        "open": [1, 1, 1, 1],
        "fist": [0, 0, 0, 0],
        "v": [1, 1, 0, 0],
        "point": [1, 0, 0, 0],
    }[pose]
    lm = [(0.0, 0.0)] * 21
    lm[0] = (cx, cy + s)                          # 손목
    for i in range(1, 5):                          # 엄지 (판별에 안 씀)
        lm[i] = (cx - 0.4 * s - 0.1 * s * i, cy + s - 0.2 * s * i)
    for f, ext in enumerate(extended):
        mcp_i = 5 + 4 * f
        mx = cx + (f - 1.5) * 0.25 * s
        lm[mcp_i] = (mx, cy)                       # 손가락 뿌리
        if ext:
            lm[mcp_i + 1] = (mx, cy - 0.4 * s)     # 가운데 마디
            lm[mcp_i + 2] = (mx, cy - 0.65 * s)
            lm[mcp_i + 3] = (mx, cy - 0.9 * s)     # 손끝: 손목에서 더 멂
        else:
            lm[mcp_i + 1] = (mx, cy - 0.3 * s)
            lm[mcp_i + 2] = (mx, cy - 0.1 * s)
            lm[mcp_i + 3] = (mx, cy + 0.1 * s)     # 손끝: 손바닥 쪽으로 접힘
    lm[9] = (cx, cy)  # 손목~중지 뿌리 = s
    return Hand(label=label, score=0.99, landmarks=lm)


class Sim:
    """30fps로 프레임을 흘려보내며 이벤트를 모읍니다."""

    def __init__(self):
        self.rec = GestureRecognizer()
        self.t = 0.0
        self.events = []

    def frames(self, n, make=None):
        for i in range(n):
            hands = make(i) if make else []
            if hands is not None and not isinstance(hands, list):
                hands = [hands]
            self.events += self.rec.update(hands, self.t)
            self.t += DT

    def hold(self, pose, sec, **kw):
        self.frames(round(sec * FPS), lambda i: make_hand(pose, **kw))

    def move(self, sec, x0, y0, x1, y1, **kw):
        n = round(sec * FPS)
        self.frames(n, lambda i: make_hand("open", x0 + (x1 - x0) * (i + 1) / n, y0 + (y1 - y0) * (i + 1) / n, **kw))

    def activate(self, **kw):
        self.hold("v", 1.3, **kw)
        self.hold("open", 1.2, **kw)  # 전환 쿨다운이 끝나고 손을 멈춰 준비 상태로

    def commands(self):
        return [e.command for e in self.events if e.type == EventType.COMMAND]

    def types(self):
        return [e.type for e in self.events]

    def clear(self):
        self.events = []


class PoseTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify_pose(make_hand("open").landmarks), Pose.OPEN)
        self.assertEqual(classify_pose(make_hand("fist").landmarks), Pose.FIST)
        self.assertEqual(classify_pose(make_hand("v").landmarks), Pose.V_SIGN)
        self.assertEqual(classify_pose(make_hand("point").landmarks), Pose.OTHER)


class ActivationTest(unittest.TestCase):
    def test_nothing_runs_before_activation(self):
        sim = Sim()
        sim.hold("open", 1.0)
        sim.move(0.3, 320, 240, 520, 240)
        sim.hold("fist", 0.3)
        sim.hold("open", 0.3)
        self.assertEqual(sim.commands(), [])

    def test_v_hold_toggles_once_per_hold(self):
        sim = Sim()
        sim.hold("v", 0.5)
        self.assertEqual(sim.types(), [])          # 1초가 안 됨
        sim.hold("v", 2.5)                          # 계속 유지해도 한 번만
        self.assertEqual(sim.types(), [EventType.ACTIVATED])
        sim.hold("open", 0.3)
        sim.hold("v", 1.3)                          # 손을 바꿨다가 다시 V -> 종료
        self.assertEqual(sim.types(), [EventType.ACTIVATED, EventType.DEACTIVATED])
        self.assertFalse(sim.rec.active)


class CommandTest(unittest.TestCase):
    def test_fist_then_open_is_play_pause_once(self):
        sim = Sim()
        sim.activate()
        sim.hold("fist", 0.3)
        sim.hold("open", 1.5)                       # 편 채로 유지해도 반복 실행 안 됨
        self.assertEqual(sim.commands(), [Command.PLAY_PAUSE])

    def test_slow_fist_to_open_is_ignored(self):
        sim = Sim()
        sim.activate()
        sim.hold("fist", 0.3)
        sim.hold("point", 1.0)                      # 너무 천천히 폄
        sim.hold("open", 0.5)
        self.assertEqual(sim.commands(), [])

    def test_four_directions(self):
        cases = [
            ((320, 240, 520, 240), Command.SEEK_FORWARD_10),
            ((320, 240, 120, 240), Command.SEEK_BACK_10),
            ((320, 300, 320, 140), Command.VOLUME_UP),
            ((320, 160, 320, 320), Command.VOLUME_DOWN),
        ]
        for (x0, y0, x1, y1), expected in cases:
            with self.subTest(expected=expected):
                sim = Sim()
                sim.hold("v", 1.3)
                sim.hold("open", 1.2, cx=x0, cy=y0)
                sim.move(0.3, x0, y0, x1, y1)
                self.assertEqual(sim.commands(), [expected])

    def test_left_hand_works_the_same(self):
        sim = Sim()
        sim.activate(label="Left")
        sim.move(0.3, 320, 240, 520, 240, label="Left")
        self.assertEqual(sim.commands(), [Command.SEEK_FORWARD_10])

    def test_diagonal_and_slow_moves_ignored(self):
        sim = Sim()
        sim.activate()
        sim.move(0.3, 320, 240, 480, 400)           # 대각선
        sim.hold("open", 0.6, cx=480, cy=400)
        sim.move(3.0, 480, 400, 200, 400)           # 아주 천천히
        self.assertEqual(sim.commands(), [])


class SafetyTest(unittest.TestCase):
    def test_return_motion_does_not_trigger_opposite(self):
        sim = Sim()
        sim.activate()
        sim.move(0.3, 320, 240, 520, 240)
        sim.move(0.3, 520, 240, 320, 240)           # 바로 제자리로 되돌림
        self.assertEqual(sim.commands(), [Command.SEEK_FORWARD_10])

    def test_cooldown_blocks_fast_second_command(self):
        sim = Sim()
        sim.activate()
        sim.move(0.3, 320, 240, 520, 240)
        sim.hold("open", 0.35, cx=520, cy=240)      # 멈춰서 준비는 됐지만 아직 쿨다운 중
        sim.move(0.2, 520, 240, 320, 240)
        self.assertEqual(sim.commands(), [Command.SEEK_FORWARD_10])
        self.assertIn(EventType.IGNORED, sim.types())

    def test_second_command_after_cooldown(self):
        sim = Sim()
        sim.activate()
        sim.move(0.3, 320, 240, 520, 240)
        sim.hold("open", 1.2, cx=520, cy=240)
        sim.move(0.3, 520, 240, 320, 240)
        self.assertEqual(sim.commands(), [Command.SEEK_FORWARD_10, Command.SEEK_BACK_10])

    def test_hand_lost_resets_pending_gesture(self):
        sim = Sim()
        sim.activate()
        sim.hold("fist", 0.3)
        # 손이 0.6초 사라짐 (HAND_LOST_RESET_SEC=0.5 초과). 초기화가 없다면
        # 주먹 후 0.7초 만에 편 것이라 재생/정지가 실행됐을 상황
        sim.frames(round(0.6 * FPS))
        sim.hold("open", 0.5)
        self.assertEqual(sim.commands(), [])

    def test_short_dropout_is_tolerated(self):
        sim = Sim()
        sim.activate()
        sim.hold("fist", 0.3)
        sim.frames(round(0.2 * FPS))                # 빠른 동작으로 0.2초 놓침 -> 이어서 판별
        sim.hold("open", 0.3)
        self.assertEqual(sim.commands(), [Command.PLAY_PAUSE])

    def test_auto_deactivate_without_hands(self):
        sim = Sim()
        sim.activate()
        sim.frames(round(11 * FPS))
        self.assertEqual(sim.types()[-1], EventType.DEACTIVATED)
        self.assertFalse(sim.rec.active)

    def test_one_command_per_frame_with_two_hands(self):
        sim = Sim()
        sim.hold("v", 1.3)
        sim.frames(round(1.2 * FPS), lambda i: [make_hand("open", 200, 240, "Left"),
                                                make_hand("open", 440, 240, "Right")])
        n = round(0.3 * FPS)
        sim.frames(n, lambda i: [make_hand("open", 200 - 200 * (i + 1) / n, 240, "Left"),
                                 make_hand("open", 440 + 200 * (i + 1) / n, 240, "Right")])
        self.assertEqual(len(sim.commands()), 1)


if __name__ == "__main__":
    unittest.main()
