"""UI용 작업 스레드 테스트 — 가짜 카메라·손 인식·유튜브 백엔드로 실행 (웹캠·유튜브·키 입력 없음)."""
import queue
import threading
import time
import unittest

import numpy as np

from gesture_control.common import Command, EventType
from gesture_control.gestures import GestureRecognizer
from gesture_control.workers import CameraWorker, ControlWorker, DiscoveryWorker
from gesture_control.youtube_target import NO_ACCESS, NO_VIDEO, VIDEO, Target
from tests.test_controller import APP, TAB, FakeBackend
from tests.test_gestures import make_hand


class FakeCamera:
    def __init__(self):
        self.released = False

    def read(self):
        time.sleep(1 / 30)
        return np.zeros((480, 640, 3), np.uint8)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.released = True


class FakeTracker:
    def __init__(self):
        self.pose = None          # None = 손 없음
        self.closed = False

    def detect(self, frame, ts):
        return [make_hand(self.pose)] if self.pose else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


def wait_until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class CameraWorkerTest(unittest.TestCase):
    def setUp(self):
        self.posts = queue.Queue()
        self.cam, self.tracker = FakeCamera(), FakeTracker()
        self.commands = []
        self.w = CameraWorker(lambda k, v: self.posts.put((k, v)), self.commands.append,
                              camera_factory=lambda: self.cam, tracker_factory=lambda: self.tracker)
        self.w.start()

    def tearDown(self):
        self.w.stop()
        self.w.join(3)

    def events(self):
        out = []
        while not self.posts.empty():
            k, v = self.posts.get()
            if k == "event":
                out.append(v.type)
        return out

    def test_button_and_v_sign_share_one_state(self):
        self.w.request_active(True)                                   # 버튼으로 시작
        self.assertTrue(wait_until(lambda: self.w.latest().active))
        self.tracker.pose = "v"                                       # V 사인 1초 -> 종료
        self.assertTrue(wait_until(lambda: not self.w.latest().active, 3))
        self.w.request_active(True)                                   # V를 든 채 버튼으로 다시 시작
        self.assertTrue(wait_until(lambda: self.w.latest().active))
        time.sleep(1.5)                                               # 들고 있던 V로 곧바로 꺼지지 않음
        self.assertTrue(self.w.latest().active)
        self.assertEqual(self.events(), [EventType.ACTIVATED, EventType.DEACTIVATED, EventType.ACTIVATED])

    def test_button_same_state_is_ignored(self):
        self.w.request_active(False)
        time.sleep(0.3)
        self.assertEqual(self.events(), [])

    def test_stop_releases_camera_and_tracker(self):
        self.assertTrue(wait_until(lambda: self.w.latest().running))
        self.assertIsNotNone(self.w.latest().frame_rgb)
        self.w.stop()
        self.w.join(3)
        self.assertFalse(self.w.is_alive())
        self.assertTrue(self.cam.released)
        self.assertTrue(self.tracker.closed)


class CameraErrorTest(unittest.TestCase):
    def test_camera_open_failure_is_reported(self):
        posts = []

        def broken():
            raise RuntimeError("웹캠(0번)을 열 수 없습니다")

        w = CameraWorker(lambda k, v: posts.append((k, v)), lambda c: None, camera_factory=broken,
                         tracker_factory=FakeTracker)
        w.start()
        w.join(3)
        self.assertFalse(w.is_alive())
        self.assertIn("error", [k for k, _ in posts])
        self.assertIn("열 수 없습니다", w.latest().error)


class ControlWorkerTest(unittest.TestCase):
    def start(self, targets):
        self.posts = queue.Queue()
        self.pressed = []
        self.backend = FakeBackend(targets=targets)
        self.w = ControlWorker(lambda k, v: self.posts.put((k, v)), backend_factory=lambda: self.backend,
                               press=lambda vk, ext: self.pressed.append(vk), verify_delay=0)
        self.w.start()

    def tearDown(self):
        self.w.stop()
        self.w.join(3)

    def wait_post(self, kind, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                k, v = self.posts.get(timeout=0.1)
            except queue.Empty:
                continue
            if k == kind:
                return v
        self.fail(f"{kind} 메시지가 오지 않음")

    def wait_status(self, status, timeout=2.0):
        """대상 상태 메시지 중 원하는 상태가 올 때까지 기다림."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            v = self.wait_post("target", timeout=max(0.1, end - time.monotonic()))
            if v[1] == status:
                return v
        self.fail(f"대상 상태 {status} 가 오지 않음")

    def test_single_target_auto_selected_and_test_mode_sends_nothing(self):
        self.start([APP])
        self.w.refresh()
        self.assertEqual(self.wait_post("targets")[1], 0)
        self.w.submit(Command.PLAY_PAUSE)
        cmd, result, ident = self.wait_post("result")
        self.assertFalse(result.sent)
        self.assertIn("[테스트]", result.message)
        self.assertEqual(self.pressed, [])
        self.assertNotIn("prepare", self.backend.calls)

    def test_multiple_targets_need_selection_then_live_sends_once(self):
        self.start([APP, TAB])
        self.w.refresh()
        self.assertIsNone(self.wait_post("targets")[1])          # 여러 개면 자동 선택 안 함
        self.assertIsNone(self.wait_post("target")[0])            # 현재 대상: 없음
        self.w.select(1)
        self.assertIn("브라우저", self.wait_post("target")[0])
        self.w.set_live(True)
        self.w.submit(Command.VOLUME_UP)
        cmd, result, ident = self.wait_post("result")
        self.assertTrue(result.sent)
        self.assertEqual(self.pressed, [0x26])
        self.assertIn("hwnd=200", ident)

    def test_switch_app_to_browser_then_commands_never_reach_app(self):
        self.start([APP, TAB])
        self.w.refresh()
        self.w.select(0)
        self.wait_post("log")                                     # 선택이 처리된 뒤 제스처
        self.w.set_live(True)
        self.w.submit(Command.PLAY_PAUSE)
        self.wait_post("result")
        self.w.select(1)                                          # 앱 -> 브라우저
        self.assertIn("대상 변경", self.wait_post("log"))
        for cmd in (Command.PLAY_PAUSE, Command.PLAY_PAUSE, Command.VOLUME_DOWN, Command.SEEK_FORWARD_10):
            self.w.submit(cmd)
        idents = [self.wait_post("result")[2] for _ in range(4)]
        self.assertTrue(all("hwnd=200" in i for i in idents))
        self.assertEqual(self.backend.prepared_for, [100, 200, 200, 200, 200])
        self.assertIn("reset_cache", self.backend.calls)          # 이전 대상의 플레이어 정보 폐기

    def test_selection_kept_when_other_window_added(self):
        self.start([APP, TAB])
        self.w.refresh()
        self.assertEqual(self.wait_post("target")[1], "choose")
        self.w.select(1)
        self.assertEqual(self.wait_post("target")[1], "manual")
        other = Target(300, "browser", "Firefox", "새 영상", (5, 5), True, VIDEO, 3, 1)
        self.backend.targets = [APP, TAB, other]                  # 다른 창 추가 + 새로고침
        self.w.refresh()
        names, idx = self.wait_post("targets")
        self.assertEqual((len(names), idx), (3, 1))
        self.assertEqual(self.w.controller.target.hwnd, 200)

    def test_closed_target_cancels_queued_commands_and_new_gestures_use_new_target(self):
        self.start([APP, TAB])
        self.w.refresh()
        self.w.select(1)
        self.w.set_live(True)
        self.wait_status("manual")
        old_gen = self.w._gen
        self.backend.targets = [APP]                              # 선택한 브라우저 탭이 닫힘
        self.w.refresh()
        self.wait_status("auto")                                  # 남은 하나 자동 선택
        self.w._jobs.put(("command", Command.PLAY_PAUSE, time.monotonic(), old_gen))  # 닫히기 전 제스처
        cmd, result, ident = self.wait_post("result")
        self.assertIn("[취소]", result.message)
        self.w.submit(Command.VOLUME_UP)                          # 새 제스처
        cmd, result, ident = self.wait_post("result")
        self.assertTrue(result.sent)
        self.assertIn("hwnd=100", ident)
        self.assertEqual(self.backend.prepared_for, [100])        # 닫힌 탭·이전 명령은 전송 없음

    def test_stale_command_is_not_executed(self):
        self.start([APP])
        self.w.refresh()
        self.w.set_live(True)
        self.wait_post("live")
        self.w._jobs.put(("command", Command.PLAY_PAUSE, time.monotonic() - 5, self.w._gen))
        cmd, result, ident = self.wait_post("result")
        self.assertFalse(result.sent)
        self.assertIn("[취소]", result.message)
        self.assertEqual(self.pressed, [])

    def test_stop_ends_thread(self):
        self.start([])
        self.w.stop()
        self.w.join(2)
        self.assertFalse(self.w.is_alive())

    def test_no_access_targets_are_not_auto_selected(self):
        chrome = Target(500, "browser", "Chrome", "영상", (8, 1), True, NO_ACCESS, 1, 1)
        self.start([chrome])
        self.w.refresh()
        self.assertEqual(self.wait_post("targets")[1], None)
        desc, status, page, count = self.wait_post("target")
        self.assertEqual((desc, status, count), (None, "blocked", 0))
        self.assertIn("제어 불가", chrome.describe())

    def test_no_video_pages_do_not_count_for_auto_select(self):
        home = Target(400, "browser", "Edge", "", (7, 1), True, NO_VIDEO, 1, 1)
        self.start([home, APP])
        self.w.refresh()
        self.assertEqual(self.wait_post("targets")[1], 1)          # 영상 있는 APP만 자동 선택
        self.assertEqual(self.wait_post("target")[1], "auto")


class AutoDiscoveryTest(unittest.TestCase):
    """DiscoveryWorker + ControlWorker: 수동 새로고침 없이 대상 자동 발견·선택."""

    def setUp(self):
        self.posts = queue.Queue()
        self.backend = FakeBackend(targets=[])
        self.control = ControlWorker(lambda k, v: self.posts.put((k, v)), backend_factory=lambda: self.backend,
                                     press=lambda vk, ext: None, verify_delay=0)
        self.disc = DiscoveryWorker(self.control.offer_targets, lambda k, v: self.posts.put((k, v)),
                                    backend_factory=lambda: self.backend, interval=0.05)
        self.control.start()
        self.disc.start()

    def tearDown(self):
        self.disc.stop()
        self.control.stop()
        self.disc.join(2)
        self.control.join(2)

    def last_target(self, timeout=2.0):
        end, last = time.monotonic() + timeout, None
        while time.monotonic() < end:
            try:
                k, v = self.posts.get(timeout=0.1)
            except queue.Empty:
                if last is not None:
                    return last
                continue
            if k == "target":
                last = v
        return last

    def test_empty_then_opened_youtube_is_found_and_auto_selected(self):
        self.assertEqual(self.last_target()[1], "empty")          # '유튜브 영상을 열어 주세요'
        self.backend.targets = [TAB]                              # 프로그램 실행 후 유튜브를 엶
        desc, status, page, count = self.last_target()
        self.assertEqual(status, "auto")
        self.assertIn("브라우저", desc)
        self.assertNotIn("prepare", self.backend.calls)          # 자동 선택만으로 포커스·제어 안 함

    def test_auto_selected_target_is_kept_when_another_browser_opens(self):
        edge = Target(600, "browser", "Edge", "엣지 영상", (1, 1), True, VIDEO, 1, 1)
        firefox = Target(700, "browser", "Firefox", "파이어폭스 영상", (2, 1), True, VIDEO, 2, 1)
        self.backend.targets = [edge]
        self.assertEqual(self.last_target()[1], "auto")           # Edge 하나 -> 자동 선택
        self.backend.targets = [edge, firefox]                    # Firefox 추가로 열림
        desc, status, page, count = self.last_target()
        self.assertEqual((status, count), ("auto", 2))             # '고르세요'로 바뀌지 않음
        self.assertIn("Edge", desc)
        self.assertEqual(self.control.controller.target.hwnd, 600)

    def test_two_targets_ask_user(self):
        self.backend.targets = [APP, TAB]
        desc, status, page, count = self.last_target()
        self.assertEqual((desc, status, count), (None, "choose", 2))

    def test_discovery_stops_and_survives_errors(self):
        def boom():
            raise RuntimeError("창이 닫히는 중")
        self.backend.find_targets = boom
        time.sleep(0.2)
        self.assertTrue(self.disc.is_alive())                     # 오류가 나도 검색은 계속
        self.disc.stop()
        self.disc.join(2)
        self.assertFalse(self.disc.is_alive())


class SetActiveTest(unittest.TestCase):
    def test_set_active_applies_cooldown_like_v_sign(self):
        rec = GestureRecognizer()
        ev = rec.set_active(True, 10.0)
        self.assertEqual(ev.type, EventType.ACTIVATED)
        self.assertTrue(rec.active)
        self.assertGreater(rec.cooldown_left(10.0), 0)
        self.assertIsNone(rec.set_active(True, 10.5))


if __name__ == "__main__":
    unittest.main()
