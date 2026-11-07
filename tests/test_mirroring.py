"""좌우 반전 처리 테스트.

MediaPipe에는 카메라 원본을 넣고(Left/Right = 사용자 실제 손), 좌표만 거울 화면 기준으로 바꿉니다.
카메라는 사용자를 마주 보므로, 사용자가 자기 오른쪽으로 손을 움직이면 원본 영상에서는 x가 작아집니다.
"""
import unittest

from gesture_control.common import Command, Hand
from gesture_control.gestures import GestureRecognizer
from gesture_control.hand_tracker import to_view_coords
from tests.test_gestures import DT, make_hand

W, H = 640, 480


def raw_hand(raw_x: float, label: str, pose: str = "open") -> Hand:
    """원본 영상 기준 정규화 좌표 raw_x(0~1)에 있는 손을 HandTracker와 같은 방식으로 변환."""
    template = make_hand(pose, cx=raw_x * W, cy=240)
    raw_norm = [(x / W, y / H) for x, y in template.landmarks]
    return Hand(label=label, score=0.99, landmarks=to_view_coords(raw_norm, W, H))


class MirrorTest(unittest.TestCase):
    def test_x_is_flipped_y_is_kept(self):
        self.assertEqual(to_view_coords([(0.2, 0.3)], W, H), [(0.8 * W, 0.3 * H)])

    def test_user_right_hand_appears_on_right_of_preview(self):
        # 마주 보는 카메라 원본에서 사용자 오른손은 영상 왼쪽(x 작음)에 찍힘
        hand = raw_hand(0.25, "Right")
        self.assertGreater(hand.landmarks[0][0], W / 2)

    def _swipe(self, raw_from: float, raw_to: float, label: str):
        rec, t, cmds = GestureRecognizer(), 0.0, []

        def feed(x, n):
            nonlocal t
            for _ in range(n):
                cmds.extend(e.command for e in rec.update([raw_hand(x, label, pose)], t) if e.command)
                t += DT

        pose = "v"
        feed(raw_from, 40)       # 인식 시작
        pose = "open"
        feed(raw_from, 36)       # 쿨다운 끝 + 멈춤
        n = 9
        for i in range(n):       # 0.3초 동안 이동
            feed(raw_from + (raw_to - raw_from) * (i + 1) / n, 1)
        return cmds

    def test_moving_to_user_right_is_forward_for_both_hands(self):
        for label in ("Right", "Left"):
            with self.subTest(hand=label):
                # 사용자 오른쪽 이동 = 원본 x 감소
                self.assertEqual(self._swipe(0.6, 0.2, label), [Command.SEEK_FORWARD_10])

    def test_moving_to_user_left_is_back(self):
        self.assertEqual(self._swipe(0.4, 0.8, "Right"), [Command.SEEK_BACK_10])


if __name__ == "__main__":
    unittest.main()
