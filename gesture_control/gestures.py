"""손 제스처 판별 + 오작동 방지 (담당: 고지혁 — 샘플 구현).

이 파일은 MediaPipe·OpenCV를 import 하지 않습니다. Hand(관절 좌표)만 받아서 Event를 돌려주므로
웹캠 없이도 tests/ 의 가짜 좌표로 자동 테스트할 수 있습니다.

제스처 (어느 손이든 같은 동작 — 팀 답변으로 확정)
  V 사인 1초 유지          -> 인식 시작 / 종료 전환            [임시 동작]
  주먹 쥐었다 펴기          -> 재생 / 일시정지                 [제안서]
  편 손을 위 / 아래로 이동   -> 볼륨 증가 / 감소               [제안서]
  편 손을 왼쪽 / 오른쪽 이동 -> 10초 뒤로 / 앞으로             [제안서]

오작동 방지
  - 연속 프레임 확인: 같은 손 모양이 CONFIRM_FRAMES 프레임 연속이어야 손 모양을 바꿈
  - 쿨다운: 명령 실행 후 COOLDOWN_SEC 동안 다른 명령 무시 (두 손 공통)
  - 중복 실행 방지: 주먹->펴기는 새로 주먹을 쥐어야 다시 인정, 손 이동은 손을 잠시 멈춰야 다시 인정
                     (손을 원래 자리로 되돌리는 동작이 반대 명령으로 실행되는 것도 막음)
  - 손을 놓쳤을 때: HAND_LOST_RESET_SEC 이상 사라지면 그 손의 진행 중 판별 초기화,
                     AUTO_DEACTIVATE_SEC 동안 손이 없으면 인식 자동 종료
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from . import config as C
from .common import COMMAND_KO, Command, Event, EventType, Hand

# MediaPipe 관절 번호
WRIST = 0
MIDDLE_MCP = 9
PALM_POINTS = (0, 5, 9, 13, 17)              # 손바닥 중심 계산용 (손목 + 네 손가락 뿌리)
FINGER_PIP_TIP = ((6, 8), (10, 12), (14, 16), (18, 20))  # 검지, 중지, 약지, 새끼의 (가운데 마디, 끝)
EXTENDED_RATIO = 1.1                         # 손끝이 가운데 마디보다 손목에서 10% 이상 멀면 '편 손가락'


class Pose(Enum):
    FIST = "FIST"
    OPEN = "OPEN"
    V_SIGN = "V"
    OTHER = "OTHER"


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def fingers_extended(lm) -> list[bool]:
    """검지·중지·약지·새끼가 펴졌는지. (엄지는 방향에 따라 판정이 불안정해서 제외)

    손목에서 손끝까지 거리와 손목에서 가운데 마디까지 거리를 비교하므로
    손이 기울어져 있어도 비교적 안정적으로 판단합니다.
    """
    w = lm[WRIST]
    return [_dist(w, lm[tip]) > _dist(w, lm[pip]) * EXTENDED_RATIO for pip, tip in FINGER_PIP_TIP]


def classify_pose(lm) -> Pose:
    ext = fingers_extended(lm)
    if all(ext):
        return Pose.OPEN
    if not any(ext):
        return Pose.FIST
    if ext == [True, True, False, False]:
        return Pose.V_SIGN
    return Pose.OTHER


def palm_size(lm) -> float:
    return max(_dist(lm[WRIST], lm[MIDDLE_MCP]), 1e-6)


def palm_center(lm) -> tuple[float, float]:
    xs = [lm[i][0] for i in PALM_POINTS]
    ys = [lm[i][1] for i in PALM_POINTS]
    return sum(xs) / len(xs), sum(ys) / len(ys)


@dataclass
class _HandState:
    """손 하나(왼손/오른손)마다 따로 기억하는 판별 상태."""

    last_seen: float = -math.inf
    pose: Pose = Pose.OTHER          # 연속 프레임 확인을 통과한 손 모양
    candidate: Pose | None = None
    candidate_count: int = 0
    fist_at: float | None = None     # 마지막으로 주먹이 확인된 시각
    v_since: float | None = None     # V 사인을 시작한 시각
    v_used: bool = False             # 이번 V 사인으로 이미 전환했는지 (손을 바꿔야 다시 가능)
    armed: bool = False              # 손 이동 명령을 받을 준비가 됐는지 (잠시 멈춘 뒤 True)
    track: deque = field(default_factory=deque)  # (시각, x, y, 손바닥크기)

    def update_pose(self, raw: Pose) -> Pose:
        if raw == self.candidate:
            self.candidate_count += 1
        else:
            self.candidate, self.candidate_count = raw, 1
        if self.candidate_count >= C.CONFIRM_FRAMES:
            self.pose = raw
        return self.pose

    def reset_motion(self) -> None:
        self.track.clear()
        self.armed = False

    def reset(self) -> None:
        last_seen = self.last_seen
        self.__init__()
        self.last_seen = last_seen


class GestureRecognizer:
    def __init__(self) -> None:
        self.active = False
        self.cooldown_until = -math.inf
        self.last_hand_time: float | None = None
        self._states: dict[str, _HandState] = {}
        self.hand_info: dict[str, str] = {}   # 화면 표시용: 손 이름 -> "OPEN ready" 등

    # ------------------------------------------------------------------ 공개 함수
    def update(self, hands: list[Hand], t: float) -> list[Event]:
        """한 프레임의 손 목록과 현재 시각(초)을 받아 발생한 이벤트 목록을 돌려줍니다."""
        events: list[Event] = []
        keys = self._keys(hands)
        command_done = False

        for key, hand in zip(keys, hands):
            st = self._states.setdefault(key, _HandState())
            if t - st.last_seen > C.HAND_LOST_RESET_SEC:
                st.reset()  # 손을 놓쳤다가 다시 찾음 -> 하던 판별은 버림
            st.last_seen = t
            pose = st.update_pose(classify_pose(hand.landmarks))

            ev = self._check_activation(key, st, pose, t)
            if ev:
                events.append(ev)
                continue

            if not self.active:
                st.reset_motion()
                st.fist_at = None
                continue

            if command_done:  # 한 프레임에는 명령 하나만
                continue
            ev = self._check_play_pause(key, st, pose, t) or self._check_swipe(key, st, pose, hand.landmarks, t)
            if ev:
                events.append(ev)
                command_done = ev.type == EventType.COMMAND

        if hands:
            self.last_hand_time = t
        elif self.active and self.last_hand_time is not None and t - self.last_hand_time >= C.AUTO_DEACTIVATE_SEC:
            self._set_active(False, t)
            events.append(Event(EventType.DEACTIVATED,
                                f"손이 {C.AUTO_DEACTIVATE_SEC:.0f}초 동안 보이지 않아 인식을 종료합니다."))

        self.hand_info = {k: self._describe(self._states[k]) for k in keys}
        return events

    def cooldown_left(self, t: float) -> float:
        return max(0.0, self.cooldown_until - t)

    def set_active(self, active: bool, t: float, source: str = "버튼") -> Event | None:
        """버튼 등 외부에서 인식 시작/종료. V 사인과 같은 값(self.active)을 바꾸므로 두 방식의 상태가 항상 같습니다.

        V 사인으로 전환할 때와 똑같이 쿨다운·진행 중 판별 초기화를 적용합니다. 이미 그 상태면 None.
        """
        if active == self.active:
            return None
        self._set_active(active, t)
        for st in self._states.values():
            if st.v_since is not None:
                st.v_used = True  # 버튼을 누르는 동안 들고 있던 V 사인이 곧바로 다시 전환하지 않도록
        if active:
            return Event(EventType.ACTIVATED, f"{source} -> 인식 시작")
        return Event(EventType.DEACTIVATED, f"{source} -> 인식 종료")

    # ------------------------------------------------------------------ 판별
    def _check_activation(self, key: str, st: _HandState, pose: Pose, t: float) -> Event | None:
        if pose != Pose.V_SIGN:
            st.v_since, st.v_used = None, False
            return None
        if st.v_since is None:
            st.v_since = t
        if st.v_used or t - st.v_since < C.ACTIVATION_HOLD_SEC:
            return None
        st.v_used = True
        self._set_active(not self.active, t)
        if self.active:
            return Event(EventType.ACTIVATED, f"{key} 손 V 사인 -> 인식 시작", hand=key)
        return Event(EventType.DEACTIVATED, f"{key} 손 V 사인 -> 인식 종료", hand=key)

    def _check_play_pause(self, key: str, st: _HandState, pose: Pose, t: float) -> Event | None:
        if pose == Pose.FIST:
            st.fist_at = t
            return None
        if pose == Pose.OPEN and st.fist_at is not None:
            in_time = t - st.fist_at <= C.FIST_TO_OPEN_WINDOW_SEC
            st.fist_at = None  # 한 번 쓰면 다시 주먹을 쥐어야 함 (중복 실행 방지)
            if in_time:
                st.reset_motion()
                return self._fire(Command.PLAY_PAUSE, key, t)
        return None

    def _check_swipe(self, key: str, st: _HandState, pose: Pose, lm, t: float) -> Event | None:
        if pose != Pose.OPEN:
            st.reset_motion()
            return None

        x, y = palm_center(lm)
        size = palm_size(lm)
        st.track.append((t, x, y, size))
        horizon = max(C.SWIPE_WINDOW_SEC, C.REARM_STILL_SEC) + 0.2
        while st.track and t - st.track[0][0] > horizon:
            st.track.popleft()

        if not st.armed:
            # 손을 잠시 멈춰야 다음 이동 명령을 받음
            held_long_enough = t - st.track[0][0] >= C.REARM_STILL_SEC
            recent = [p for p in st.track if t - p[0] <= C.REARM_STILL_SEC]
            still = all(math.hypot(px - x, py - y) <= C.REARM_MAX_MOVE * size for _, px, py, _ in recent)
            if held_long_enough and still:
                st.armed = True
            return None

        window = [p for p in st.track if t - p[0] <= C.SWIPE_WINDOW_SEC]
        _, x0, y0, size0 = window[0]
        unit = (size + size0) / 2
        dx, dy = (x - x0) / unit, (y - y0) / unit

        cmd = None
        if abs(dx) >= C.SWIPE_MIN_DIST_X and abs(dx) >= C.SWIPE_AXIS_RATIO * abs(dy):
            cmd = Command.SEEK_FORWARD_10 if dx > 0 else Command.SEEK_BACK_10
        elif abs(dy) >= C.SWIPE_MIN_DIST_Y and abs(dy) >= C.SWIPE_AXIS_RATIO * abs(dx):
            cmd = Command.VOLUME_DOWN if dy > 0 else Command.VOLUME_UP  # 화면 y는 아래로 갈수록 커짐
        if cmd is None:
            return None
        st.reset_motion()  # 다시 멈출 때까지 다음 이동 무시 (되돌리는 동작 방지)
        return self._fire(cmd, key, t)

    # ------------------------------------------------------------------ 도우미
    def _fire(self, cmd: Command, key: str, t: float) -> Event:
        if t < self.cooldown_until:
            return Event(EventType.IGNORED,
                         f"{key} 손: {COMMAND_KO[cmd]} 인식, 쿨다운 중이라 무시 ({self.cooldown_left(t):.1f}초 남음)",
                         cmd, key)
        self.cooldown_until = t + C.COOLDOWN_SEC
        return Event(EventType.COMMAND, f"{key} 손: {COMMAND_KO[cmd]}", cmd, key)

    def _set_active(self, active: bool, t: float) -> None:
        self.active = active
        self.cooldown_until = t + C.COOLDOWN_SEC  # 전환 직후의 손동작이 명령으로 실행되지 않게
        self.last_hand_time = t
        for st in self._states.values():
            st.reset_motion()
            st.fist_at = None

    @staticmethod
    def _keys(hands: list[Hand]) -> list[str]:
        keys, seen = [], {}
        for h in hands:
            n = seen.get(h.label, 0)
            seen[h.label] = n + 1
            keys.append(h.label if n == 0 else f"{h.label}#{n + 1}")  # 같은 방향으로 두 손이 잡힌 경우
        return keys

    def _describe(self, st: _HandState) -> str:
        if not self.active:
            if st.v_since is not None and not st.v_used:
                return f"{st.pose.value} hold..."
            return st.pose.value
        if st.pose == Pose.OPEN:
            return "OPEN ready" if st.armed else "OPEN (hold still)"
        return st.pose.value
