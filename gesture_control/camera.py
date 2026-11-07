"""웹캠 입력 (담당: 송준섭 — 샘플 구현).

교수님 피드백 5: OpenCV는 필수가 아님. 다만 MediaPipe(Python)에는 웹캠을 여는 기능이 없어서
이 샘플은 '웹캠 열기 / 화면 표시'에만 OpenCV를 쓰고, 손 인식은 모두 MediaPipe가 담당합니다.

좌우 반전 처리 위치 (한 곳에서만 반전해야 Left/Right와 이동 방향이 꼬이지 않음)
  1) Camera.read()        : 카메라 원본 그대로 (반전 안 함)
  2) HandTracker.detect() : 원본을 MediaPipe에 전달 -> Left/Right가 사용자 실제 손 기준
                            돌려주는 좌표만 거울 좌표로 변환
  3) mirror_view()        : 미리보기 화면만 반전 (좌표와 같은 거울 공간)
"""
from __future__ import annotations

import sys

import cv2


class Camera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480):
        # Windows에서는 DirectShow가 카메라를 더 빨리 엽니다. 실패하면 기본 방식으로 다시 시도.
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(index)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"웹캠({index}번)을 열 수 없습니다. 다른 프로그램(줌, 팀즈 등)이 쓰고 있는지, "
                "Windows 설정 > 개인 정보 > 카메라 권한이 켜져 있는지 확인하세요."
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def read(self):
        """카메라 원본 프레임 1장(BGR numpy 배열, 반전 안 함)을 돌려줍니다. 읽기에 실패하면 None."""
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None
        return frame

    def release(self) -> None:
        self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def mirror_view(frame):
    """미리보기용 거울 화면(좌우 반전한 사본). Hand.landmarks 좌표와 같은 기준입니다."""
    return cv2.flip(frame, 1)
