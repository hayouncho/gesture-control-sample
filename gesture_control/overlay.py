"""미리보기 창에 손 관절과 상태 글자를 그립니다.

OpenCV의 putText는 한글을 그리지 못해서 화면 글자는 영어로 쓰고,
자세한 한국어 설명은 터미널에 출력합니다.
"""
from __future__ import annotations

import cv2
from mediapipe.tasks.python.vision import HandLandmarksConnections

from .common import Hand

_CONNECTIONS = [(c.start, c.end) for c in HandLandmarksConnections.HAND_CONNECTIONS]

GREEN = (0, 200, 0)
RED = (0, 0, 230)
YELLOW = (0, 220, 255)
WHITE = (255, 255, 255)
GRAY = (160, 160, 160)


def draw_hand(frame, hand: Hand, caption: str = "") -> None:
    pts = [(int(x), int(y)) for x, y in hand.landmarks]
    for a, b in _CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], WHITE, 2)
    for p in pts:
        cv2.circle(frame, p, 4, GREEN, -1)
    text = f"{hand.label} {hand.score:.2f}" + (f"  {caption}" if caption else "")
    x, y = pts[0]
    put_text(frame, text, (x - 40, min(frame.shape[0] - 10, y + 30)), YELLOW)


def put_text(frame, text: str, org, color=WHITE, scale: float = 0.6) -> None:
    # 배경과 상관없이 잘 보이도록 검은 테두리 + 색 글자
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def draw_lines(frame, lines: list[tuple[str, tuple[int, int, int]]], top: int = 25) -> None:
    for i, (text, color) in enumerate(lines):
        put_text(frame, text, (10, top + i * 24), color)
