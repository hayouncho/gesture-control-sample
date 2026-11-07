"""데스크톱 UI용 백그라운드 작업 (UI 코드와 분리 — 시스템 연동 담당: 조하연).

UI 스레드는 화면만 그리고, 무거운 일은 두 작업 스레드가 맡습니다.

  CameraWorker   웹캠 -> 손 인식 -> 제스처 판별 (계속 반복, 유튜브로 포커스가 가도 멈추지 않음)
                 인식 시작/종료 상태는 GestureRecognizer.active 하나뿐 — 버튼 요청도 여기서 처리
  ControlWorker  대상 선택(자동/수동), 자동 포커스, 키 전송
  DiscoveryWorker 유튜브 창/탭 자동 검색 (3초마다, 읽기 전용)
  (UI Automation은 스레드마다 따로 초기화해서 사용)

두 스레드는 결과를 콜백(post)으로 UI에 넘기고, UI는 주기적으로 꺼내서 표시합니다.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2

from . import config
from .camera import Camera, mirror_view
from .common import Command, Event, EventType
from .controller import FAILED, ControlResult, YouTubeController
from .youtube_target import NO_ACCESS, NOT_CONTROLLABLE
from .gestures import GestureRecognizer
from .hand_tracker import HandTracker
from .overlay import draw_hand

MAX_READ_FAILS = 30        # 연속으로 이만큼 프레임을 못 읽으면 카메라 작업 종료
COMMAND_MAX_WAIT = 2.0     # 제어 스레드가 바빠서 이보다 오래 기다린 명령은 실행하지 않음(늦은 실행 방지)


@dataclass
class Snapshot:
    """카메라 스레드가 매 프레임 남기는 최신 상태. UI는 이것만 읽습니다."""

    frame_rgb: object = None                 # 미리보기용 RGB 이미지(numpy)
    active: bool = False                     # 인식 중인지 (버튼·V 사인 공통)
    hands: dict = field(default_factory=dict)  # "Right" -> "OPEN ready" 등
    fps: float = 0.0
    cooldown: float = 0.0
    running: bool = False
    error: str | None = None


class CameraWorker(threading.Thread):
    def __init__(
        self,
        post: Callable[[str, object], None],
        on_command: Callable[[Command], None],
        camera_index: int = config.CAMERA_INDEX,
        camera_factory=None,
        tracker_factory=None,
    ):
        super().__init__(name="CameraWorker", daemon=True)
        self._post = post
        self._on_command = on_command
        self._camera_factory = camera_factory or (
            lambda: Camera(camera_index, config.FRAME_WIDTH, config.FRAME_HEIGHT))
        self._tracker_factory = tracker_factory or (
            lambda: HandTracker(config.MODEL_PATH, config.NUM_HANDS, config.MIN_DETECTION_CONFIDENCE,
                                config.MIN_PRESENCE_CONFIDENCE, config.MIN_TRACKING_CONFIDENCE))
        self.recognizer = GestureRecognizer()
        self._requests: queue.Queue[bool] = queue.Queue()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = Snapshot()

    # ---------------- UI 스레드에서 호출
    def request_active(self, active: bool) -> None:
        """버튼: 인식 시작/종료 요청. 실제 변경은 카메라 스레드에서 해서 V 사인과 충돌하지 않음."""
        self._requests.put(active)

    def latest(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def stop(self) -> None:
        self._stop_event.set()

    # ---------------- 카메라 스레드
    def run(self) -> None:
        try:
            with self._camera_factory() as cam, self._tracker_factory() as tracker:
                self._loop(cam, tracker)
        except Exception as e:  # 웹캠 열기 실패, 모델 없음 등
            self._set(Snapshot(error=str(e)))
            self._post("error", f"카메라/손 인식 오류: {e}")
        finally:
            with self._lock:
                self._snapshot.running = False
            self._post("camera_stopped", None)

    def _loop(self, cam, tracker) -> None:
        fps, last, fails = 0.0, time.monotonic(), 0
        while not self._stop_event.is_set():
            raw = cam.read()
            if raw is None:
                fails += 1
                if fails >= MAX_READ_FAILS:
                    raise RuntimeError("웹캠에서 영상을 계속 받지 못했습니다. 연결 상태를 확인하세요.")
                time.sleep(0.01)
                continue
            fails = 0
            now = time.monotonic()

            while not self._requests.empty():          # 버튼 요청
                ev = self.recognizer.set_active(self._requests.get(), now)
                if ev:
                    self._post("event", ev)

            hands = tracker.detect(raw, int(now * 1000))
            for ev in self.recognizer.update(hands, now):
                self._post("event", ev)
                if ev.type == EventType.COMMAND:
                    self._on_command(ev.command)

            frame = mirror_view(raw)
            for key, hand in zip(GestureRecognizer._keys(hands), hands):
                draw_hand(frame, hand, self.recognizer.hand_info.get(key, ""))
            fps = 0.9 * fps + 0.1 / max(now - last, 1e-6)
            last = now
            self._set(Snapshot(
                frame_rgb=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                active=self.recognizer.active,
                hands=dict(self.recognizer.hand_info),
                fps=fps,
                cooldown=self.recognizer.cooldown_left(now),
                running=True,
            ))

    def _set(self, snap: Snapshot) -> None:
        with self._lock:
            self._snapshot = snap


class ControlWorker(threading.Thread):
    """유튜브 창 관련 작업을 순서대로 처리. 명령 실행에 1~2초 걸려도 카메라·UI는 계속 돕니다."""

    def __init__(self, post: Callable[[str, object], None], backend_factory=None, press=None, verify_delay=0.25):
        super().__init__(name="ControlWorker", daemon=True)
        self._post = post
        self._backend_factory = backend_factory   # 테스트에서 가짜 백엔드 주입
        self._jobs: queue.Queue = queue.Queue()
        self._targets: list = []
        self._gen = 0                 # 대상이 바뀔 때마다 증가 -> 이전 대상용으로 대기 중이던 명령 취소
        self._mode = ""               # "auto"(자동 선택) / "manual"(사용자 선택)
        self._last_view = None        # UI에 마지막으로 보낸 목록·상태 (바뀔 때만 다시 보냄)
        kwargs = {"press": press} if press else {}  # 테스트에서 가짜 키 입력 주입
        self.controller = YouTubeController(live=False, verify_delay=verify_delay, **kwargs)

    # ---------------- UI/카메라/검색 스레드에서 호출
    def refresh(self) -> None:
        """이 스레드에서 직접 목록 검색 (자동 검색 스레드가 없을 때용)."""
        self._jobs.put(("refresh",))

    def offer_targets(self, targets: list) -> None:
        """자동 검색 스레드(DiscoveryWorker)가 찾은 목록을 넘김."""
        self._jobs.put(("found", targets))

    def republish(self) -> None:
        self._jobs.put(("republish",))

    def select(self, index: int) -> None:
        self._jobs.put(("select", index))

    def set_live(self, live: bool) -> None:
        self._jobs.put(("live", live))

    def submit(self, cmd: Command) -> None:
        # 제스처가 나온 시점의 대상 세대를 함께 기록 (그 사이 대상이 바뀌면 실행하지 않음)
        self._jobs.put(("command", cmd, time.monotonic(), self._gen))

    def stop(self) -> None:
        self._jobs.put(("stop",))

    # ---------------- 제어 스레드
    def run(self) -> None:
        if self._backend_factory is not None:
            self._serve(self._backend_factory)
            return
        import uiautomation as auto  # UI Automation(COM)은 사용하는 스레드에서 초기화해야 함

        with auto.UIAutomationInitializerInThread():
            from .youtube_target import UIABackend
            self._serve(UIABackend)

    def _serve(self, factory) -> None:
        try:
            self.controller.backend = factory()
        except Exception as e:
            self._post("error", f"유튜브 창 제어 기능을 준비하지 못했습니다: {e}")
        while True:
            job = self._jobs.get()
            kind = job[0]
            if kind == "stop":
                break
            try:
                if kind == "refresh":
                    backend = self.controller.backend
                    self._apply(backend.find_targets() if backend else [])
                elif kind == "found":
                    self._apply(job[1])
                elif kind == "republish":
                    self._last_view = None
                elif kind == "select":
                    self._select(job[1])
                elif kind == "live":
                    self.controller.live = job[1]
                    self._post("live", job[1])
                elif kind == "command":
                    self._command(job[1], job[2], job[3])
            except Exception as e:  # 한 작업이 실패해도 스레드는 계속
                self._post("error", f"제어 작업 오류: {e}")
        self._post("control_stopped", None)

    def _apply(self, targets: list) -> None:
        """새 목록 반영 (읽기 전용 정보만 사용 — 포커스·재생 상태를 바꾸지 않음).

        - 선택한 대상이 목록에 있으면 선택 유지 (다른 창이 추가돼도 그대로)
        - 선택한 대상이 닫혔으면 선택 해제 + 대기 중 명령 취소
        - 선택이 없을 때 제어 가능한 대상이 1개면 자동 선택, 여러 개면 선택 안내, 없으면 '영상을 열어 주세요'
        """
        self._targets = list(targets)
        cur = self.controller.target
        if cur is not None:
            match = next((t for t in self._targets if t.same_as(cur)), None)
            if match is not None:
                self.controller.target = match            # 제목·현재 탭 여부 등 최신 정보로 갱신
            else:
                backend = self.controller.backend
                alive, why = backend.is_alive(cur) if backend else (False, "대상 없음")
                if not alive:                             # 목록에서 빠진 것이 아니라 실제로 닫힘
                    self._clear_target(f"선택한 대상이 닫혔습니다({why}). 대기 중이던 명령은 취소됩니다")
        if self.controller.target is None:
            controllable = self._controllable()
            if len(controllable) == 1:
                self._set_target(controllable[0], "자동 선택", mode="auto")
        self._publish()

    def _controllable(self) -> list:
        """자동 선택 대상: 영상 페이지이거나 영상 여부를 아직 모르는 뒤쪽 탭 (영상 없음·웹 정보 없음 제외)."""
        return [t for t in self._targets if t.page not in NOT_CONTROLLABLE]

    def _status(self) -> str:
        if self.controller.target is not None:
            return self._mode or "manual"
        if len(self._controllable()) > 1:
            return "choose"
        if any(t.page == NO_ACCESS for t in self._targets):
            return "blocked"     # 유튜브는 열려 있지만 웹 정보를 읽을 수 없는 브라우저뿐
        return "empty"

    def _publish(self) -> None:
        """목록·선택 상태를 UI에 보냄 (바뀌었을 때만)."""
        t = self.controller.target
        idx = next((i for i, x in enumerate(self._targets) if t is not None and x.same_as(t)), None)
        names = [x.describe() for x in self._targets]
        status = self._status()
        view = (tuple(names), idx, status, t.describe() if t else None)
        if view == self._last_view:
            return
        self._last_view = view
        self._post("debug", "대상 목록: " + ("; ".join(f"{x.ident()} page={x.page} {x.describe()}"
                                                     for x in self._targets) or "없음"))
        self._post("targets", (names, idx))
        n = len(self._controllable())
        self._post("target", (t.describe() if t else None, status, t.page if t else None, n))

    def _select(self, index: int) -> None:
        if 0 <= index < len(self._targets):
            self._set_target(self._targets[index], "사용자 선택", mode="manual")
            self._publish()

    def _set_target(self, target, why: str, mode: str) -> None:
        prev = self.controller.target
        changed = prev is None or not prev.same_as(target)
        self.controller.target = target
        self._mode = mode
        if changed:
            self._gen += 1                           # 이전 대상용 대기 명령은 실행하지 않음
            backend = self.controller.backend
            if backend is not None and hasattr(backend, "reset_cache"):
                backend.reset_cache()                # 이전 대상의 플레이어 정보는 쓰지 않음
            self._post("log", f"대상 변경({why}): {prev.ident() if prev else '없음'} -> {target.ident()} "
                              f"{target.describe()}")

    def _clear_target(self, why: str) -> None:
        prev = self.controller.target
        self.controller.target = None
        self._mode = ""
        self._gen += 1
        self._post("log", f"{why} ({prev.ident() if prev else '-'})")

    def _command(self, cmd: Command, queued_at: float, gen: int) -> None:
        waited = time.monotonic() - queued_at
        target = self.controller.target
        ident = target.ident() if target else "대상 없음"
        if gen != self._gen:
            result = ControlResult(False, "[취소] 제스처 이후 제어 대상이 바뀌거나 닫혀서 실행하지 않음 "
                                          "(새 대상에는 새 제스처부터 적용)", FAILED, "대기")
        elif waited > COMMAND_MAX_WAIT:
            result = ControlResult(False, f"[취소] 이전 명령 처리로 {waited:.1f}초 지연되어 실행하지 않음", FAILED, "대기")
        else:
            result = self.controller.execute(cmd)   # 선택된 대상으로만 보냄
        self._post("result", (cmd, result, ident))


AUTO_REFRESH_SEC = 3.0   # 유튜브 대상 자동 검색 간격


class DiscoveryWorker(threading.Thread):
    """유튜브 창/탭을 주기적으로 찾는 스레드 (읽기 전용).

    검색에 1초 정도 걸리므로 별도 스레드에서 하고, 결과만 ControlWorker에 넘깁니다.
    그래서 화면·손 인식·명령 실행이 검색 때문에 멈추지 않습니다.
    """

    def __init__(self, on_found: Callable[[list], None], post: Callable[[str, object], None],
                 backend_factory=None, interval: float = AUTO_REFRESH_SEC):
        super().__init__(name="DiscoveryWorker", daemon=True)
        self._on_found = on_found
        self._post = post
        self._backend_factory = backend_factory
        self._interval = interval
        self._wake = threading.Event()
        self._stop_event = threading.Event()

    def trigger(self) -> None:
        """새로고침 버튼: 기다리지 않고 바로 검색."""
        self._wake.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()

    def run(self) -> None:
        if self._backend_factory is not None:
            self._loop(self._backend_factory)
            return
        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            from .youtube_target import UIABackend
            self._loop(UIABackend)

    def _loop(self, factory) -> None:
        try:
            backend = factory()
        except Exception as e:
            self._post("error", f"유튜브 자동 검색을 시작하지 못했습니다: {e}")
            return
        while not self._stop_event.is_set():
            self._wake.clear()
            try:
                self._on_found(backend.find_targets())
            except Exception as e:  # 창이 닫히는 순간 등 일시적 오류는 다음 검색에서 회복
                self._post("debug", f"자동 검색 오류(다음 검색에서 재시도): {e}")
            self._wake.wait(self._interval)
