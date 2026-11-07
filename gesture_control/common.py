"""여러 모듈이 함께 쓰는 데이터 형식.

모듈 사이에서 주고받는 값은 여기 정의된 형식만 쓰도록 맞춰 두면
팀원 코드(웹캠/손 인식, 제스처 판별, 유튜브 제어)를 서로 바꿔 끼우기 쉽습니다.

    camera.py ──frame──▶ hand_tracker.py ──list[Hand]──▶ gestures.py ──list[Event]──▶ controller.py
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass
class Hand:
    """한 손의 인식 결과.

    landmarks: MediaPipe 손 관절 21개의 (x, y) 좌표. 미리보기(거울) 화면 기준 '픽셀' 단위라서
               가로·세로 거리를 같은 기준으로 비교할 수 있고, 사용자 오른쪽 방향 = x 증가입니다.
               0=손목, 4=엄지 끝, 8=검지 끝, 12=중지 끝, 16=약지 끝, 20=새끼 끝
    label:     사용자 본인의 실제 손 "Left"(왼손) / "Right"(오른손)
    score:     그 판단의 신뢰도(0~1)
    """

    label: str
    score: float
    landmarks: list[tuple[float, float]]


class Command(Enum):
    """유튜브에 보낼 제어 명령. 값은 화면 표시용 영문 이름입니다."""

    PLAY_PAUSE = "PLAY/PAUSE"
    VOLUME_UP = "VOLUME UP"
    VOLUME_DOWN = "VOLUME DOWN"
    SEEK_BACK_10 = "BACK 10s"
    SEEK_FORWARD_10 = "FORWARD 10s"


COMMAND_KO = {
    Command.PLAY_PAUSE: "재생/일시정지",
    Command.VOLUME_UP: "볼륨 증가",
    Command.VOLUME_DOWN: "볼륨 감소",
    Command.SEEK_BACK_10: "10초 뒤로",
    Command.SEEK_FORWARD_10: "10초 앞으로",
}


class EventType(Enum):
    ACTIVATED = "activated"      # 인식 시작
    DEACTIVATED = "deactivated"  # 인식 종료
    COMMAND = "command"          # 제어 명령 실행 요청
    IGNORED = "ignored"          # 제스처는 인식했지만 쿨다운 등으로 무시


@dataclass
class Event:
    type: EventType
    message: str                    # 터미널에 보여줄 한국어 설명
    command: Command | None = None
    hand: str | None = None         # 어느 손에서 나온 이벤트인지
