"""유튜브 제어 자동 테스트 — 실제 창·키 입력 없이 가짜 백엔드로 확인합니다."""
import unittest

from gesture_control.common import Command
from gesture_control.controller import VK_UP, YouTubeController, select_target
from gesture_control.controller import FAILED, TEST, UNVERIFIED, VERIFIED
from gesture_control.youtube_target import NO_VIDEO, VIDEO, Target, page_kind, youtube_title

APP = Target(hwnd=100, kind="app", browser="Edge", title="앱 영상", page=VIDEO, window_no=1)
TAB = Target(hwnd=200, kind="browser", browser="Edge", title="브라우저 영상", tab_id=(1, 2), selected=False,
             window_no=2, tab_no=1)
OK = (True, "", "창 활성화 -> 플레이어 포커스")


class FakeBackend:
    def __init__(self, targets=(), alive=None, prepare_result=OK, states=None):
        """alive=None 이면 '현재 targets 목록에 있으면 살아 있음'으로 판단."""
        self.targets = list(targets)
        self.alive = alive
        self.prepare_result = prepare_result
        self.states = list(states or [])
        self.calls = []
        self.prepared_for = []      # prepare가 어떤 대상으로 호출됐는지 (이전 대상 전달 여부 확인용)

    def find_targets(self):
        self.calls.append("find")
        return self.targets

    def is_alive(self, t):
        self.calls.append("is_alive")
        alive = self.alive if self.alive is not None else any(x.same_as(t) for x in self.targets)
        return (True, "OK") if alive else (False, "대상 창이 닫혔습니다")

    def prepare(self, t):
        self.calls.append("prepare")
        self.prepared_for.append(t.hwnd)
        return self.prepare_result

    def player_state(self, t):
        self.calls.append("state")
        return self.states.pop(0) if self.states else None

    def reset_cache(self):
        self.calls.append("reset_cache")


def make(live, backend, target=APP):
    pressed = []
    ctl = YouTubeController(live=live, backend=backend, target=target,
                            press=lambda vk, ext: pressed.append((vk, ext)), verify_delay=0)
    return ctl, pressed


class TestModeTest(unittest.TestCase):
    def test_test_mode_never_focuses_or_presses(self):
        backend = FakeBackend()
        ctl, pressed = make(False, backend, TAB)
        r = ctl.execute(Command.VOLUME_UP)
        self.assertFalse(r.sent)
        self.assertEqual(pressed, [])
        self.assertNotIn("prepare", backend.calls)       # 포커스를 바꾸는 함수는 호출 안 됨
        self.assertIn("탭 전환", r.message)
        self.assertIn("'Up'", r.message)

    def test_test_mode_warns_when_target_closed(self):
        ctl, pressed = make(False, FakeBackend(alive=False))
        r = ctl.execute(Command.PLAY_PAUSE)
        self.assertIn("실제 모드라면 실패", r.message)
        self.assertEqual(pressed, [])


class LiveModeTest(unittest.TestCase):
    def test_success_sends_exactly_one_key(self):
        backend = FakeBackend(states=[{"volume": 50}, {"volume": 55}])
        ctl, pressed = make(True, backend)
        r = ctl.execute(Command.VOLUME_UP)
        self.assertTrue(r.sent)
        self.assertEqual(r.outcome, VERIFIED)
        self.assertEqual(pressed, [(VK_UP, True)])
        self.assertIn("볼륨 50 -> 55", r.message)

    def test_prepare_failure_sends_nothing_and_names_stage(self):
        for stage, reason in (("창 활성화", "Windows가 창 활성화를 허용하지 않았습니다"),
                              ("플레이어 포커스", "영상 플레이어에 입력 포커스를 주지 못했습니다"),
                              ("플레이어 찾기", "영상 재생 페이지가 아닙니다"),
                              ("대상 확인", "대상 창이 닫혔습니다. 대상을 다시 선택하세요.")):
            with self.subTest(stage=stage):
                ctl, pressed = make(True, FakeBackend(prepare_result=(False, stage, reason)))
                r = ctl.execute(Command.SEEK_FORWARD_10)
                self.assertFalse(r.sent)
                self.assertEqual((r.outcome, r.stage), (FAILED, stage))
                self.assertEqual(pressed, [])
                self.assertIn(reason, r.message)
                self.assertIn(f"[실패:{stage}]", r.message)

    def test_unverified_result_is_not_resent(self):
        for states in ([], [{"paused": True}, {"paused": True}], [{"paused": None}, {"paused": None}]):
            with self.subTest(states=states):
                ctl, pressed = make(True, FakeBackend(states=states))
                r = ctl.execute(Command.PLAY_PAUSE)
                self.assertTrue(r.sent)
                self.assertEqual(r.outcome, UNVERIFIED)
                self.assertEqual(len(pressed), 1)            # 확인 실패여도 재전송 없음
                self.assertIn("다시 보내지 않았습니다", r.message)

    def test_switch_target_then_many_commands_go_only_to_new_target(self):
        for first, second in ((APP, TAB), (TAB, APP)):
            with self.subTest(first=first.kind, second=second.kind):
                backend = FakeBackend()
                ctl, pressed = make(True, backend, first)
                ctl.execute(Command.PLAY_PAUSE)
                ctl.target = second
                for cmd in (Command.PLAY_PAUSE, Command.PLAY_PAUSE, Command.VOLUME_UP,
                            Command.SEEK_BACK_10, Command.SEEK_FORWARD_10):
                    ctl.execute(cmd)
                self.assertEqual(backend.prepared_for, [first.hwnd] + [second.hwnd] * 5)
                self.assertEqual(len(pressed), 6)

    def test_no_target_sends_nothing(self):
        backend = FakeBackend()
        ctl, pressed = make(True, backend, target=None)
        self.assertFalse(ctl.execute(Command.PLAY_PAUSE).sent)
        self.assertEqual(pressed, [])
        self.assertEqual(backend.calls, [])

    def test_failed_target_is_not_replaced_automatically(self):
        backend = FakeBackend(targets=[TAB], prepare_result=(False, "대상 확인", "대상 창이 닫혔습니다"))
        ctl, _ = make(True, backend)
        ctl.execute(Command.PLAY_PAUSE)
        self.assertIs(ctl.target, APP)
        self.assertNotIn("find", backend.calls)          # 다른 창을 임의로 찾지 않음

    def test_every_command_has_a_key(self):
        ctl, pressed = make(True, FakeBackend())
        for cmd in Command:
            self.assertTrue(ctl.execute(cmd).sent)
        self.assertEqual([vk for vk, _ in pressed], [0x4B, 0x26, 0x28, 0x4A, 0x4C])


class SelectionTest(unittest.TestCase):
    def test_single_target_is_auto_selected(self):
        asked = []
        t = select_target(FakeBackend(targets=[APP]), ask=lambda p: asked.append(p) or "")
        self.assertIs(t, APP)
        self.assertEqual(asked, [])

    def test_multiple_targets_ask_user(self):
        answers = iter(["9", "x", "2"])
        t = select_target(FakeBackend(targets=[APP, TAB]), ask=lambda p: next(answers))
        self.assertIs(t, TAB)

    def test_skip_or_none(self):
        self.assertIsNone(select_target(FakeBackend(targets=[APP, TAB]), ask=lambda p: ""))
        self.assertIsNone(select_target(FakeBackend(targets=[])))


class TitleTest(unittest.TestCase):
    def test_title_ignores_suffixes_added_by_browser(self):
        # 이번 버그: 재생이 시작되면 탭 이름 뒤에 표시가 붙어 '유튜브 아님'으로 판정됐음
        cases = {
            "(12)예시 영상 제목 - YouTube - 메모리 사용량 - 710 MB": "예시 영상 제목",
            "(12)예시 영상 제목 - YouTube - 오디오 재생 중 - 메모리 사용량 - 710 MB": "예시 영상 제목",
            "(12)예시 영상 제목 - YouTube - Audio playing": "예시 영상 제목",
            "예시 영상 제목 - YouTube - 탭 음소거됨": "예시 영상 제목",
            "예시 영상 제목 - YouTube (오디오 재생 중)": "예시 영상 제목",
            "예시 영상 제목 - YouTube, 오디오 재생 중": "예시 영상 제목",
            "예시 영상 제목 - YouTube · 재생 중": "예시 영상 제목",
            "제목 - 부제 - YouTube": "제목 - 부제",
            "YouTube": "",
            "YouTube - 메모리 사용량 - 100 MB": "",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(youtube_title(name), expected)

    def test_not_youtube(self):
        for name in ("youtube - Search", "YouTube Studio 사용법 - 블로그", "음악 - YouTube Music", "", "Claude"):
            with self.subTest(name=name):
                self.assertIsNone(youtube_title(name))

    def test_page_kind(self):
        self.assertEqual(page_kind("https://www.youtube.com/watch?v=abc&t=5s"), VIDEO)
        self.assertEqual(page_kind("https://www.youtube.com/"), NO_VIDEO)
        self.assertEqual(page_kind("https://www.youtube.com/results?search_query=x"), NO_VIDEO)
        self.assertEqual(page_kind("https://www.youtube.com/shorts/abc"), NO_VIDEO)

    def test_describe_distinguishes_windows_tabs_and_pages(self):
        a = Target(1, "browser", "Edge", "영상 A", (9, 1), True, VIDEO, window_no=1, tab_no=1)
        b = Target(1, "browser", "Edge", "", (9, 2), False, NO_VIDEO, window_no=1, tab_no=2)
        c = Target(2, "app", "Edge", "영상 C", None, True, VIDEO, window_no=2)
        self.assertIn("창1 · 탭1 · 현재 탭] 영상 A", a.describe())
        self.assertIn("창1 · 탭2 · 뒤에 있는 탭] 유튜브 홈 — 영상 선택 필요", b.describe())
        self.assertIn("[Edge 유튜브 앱 · 창2] 영상 C", c.describe())
        self.assertFalse(a.same_as(b))
        self.assertTrue(a.same_as(Target(1, "browser", "Edge", "다른 제목", (9, 1))))


if __name__ == "__main__":
    unittest.main()
