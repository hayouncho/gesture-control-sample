"""MediaPipe 손 검출·추적 (담당: 송준섭 — 샘플 구현).

MediaPipe 1.x 에는 예전 예제의 `mp.solutions.hands` 가 없고 Tasks API(`HandLandmarker`)를 씁니다.

공부할 핵심 API (교수님 피드백 5):
  - BaseOptions(model_asset_buffer=...)     : 모델 파일(.task) 지정
  - HandLandmarkerOptions(running_mode=VIDEO, num_hands=2, ...)
        running_mode  IMAGE(사진 1장) / VIDEO(연속 프레임, 동기) / LIVE_STREAM(비동기 콜백)
        num_hands     최대 몇 손까지 찾을지
        min_*_confidence  검출/존재/추적 신뢰도 기준
  - HandLandmarker.create_from_options(options)
  - landmarker.detect_for_video(mp.Image, timestamp_ms) -> HandLandmarkerResult
        result.hand_landmarks[i]  : 21개 관절의 정규화 좌표(x, y는 0~1, z는 손목 기준 깊이)
        result.handedness[i][0]   : category_name("Left"/"Right"), score
            -> '사용자(찍히는 사람)'의 실제 손 기준. 단, 좌우 반전된 영상을 넣으면 반대로 나옴
               (HandLandmarkerResult 설명: "Passing a horizontally mirrored image will invert these outputs.")
               그래서 MediaPipe에는 반드시 카메라 원본을 넣고, 거울 표시는 좌표 변환으로 처리합니다.
               ※ 예전 mp.solutions.hands 는 반전된 영상을 기준으로 했으므로 옛 예제와 다릅니다.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

from .common import Hand


def to_view_coords(points, width: int, height: int) -> list[tuple[float, float]]:
    """MediaPipe 정규화 좌표(원본 영상 기준, 0~1) -> 거울 미리보기 화면의 픽셀 좌표.

    카메라는 사용자를 마주 보므로 원본 영상에서는 사용자 오른쪽이 x 감소 방향입니다.
    x를 뒤집으면 '사용자 오른쪽 = x 증가'가 되어 제스처 방향과 화면 표시가 모두 사용자 기준이 됩니다.
    """
    return [((1.0 - x) * width, y * height) for x, y in points]


class HandTracker:
    def __init__(
        self,
        model_path: Path,
        num_hands: int = 2,
        min_detection_confidence: float = 0.6,
        min_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ):
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"모델 파일이 없습니다: {model_path}\n먼저 `python download_model.py` 를 실행하세요.")
        # 경로에 한글(예: '바탕 화면')이 있으면 MediaPipe가 파일을 못 여는 경우가 있어
        # 파일 내용을 직접 읽어서 넘깁니다.
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_ts = -1

    def detect(self, frame_bgr, timestamp_ms: int) -> list[Hand]:
        """카메라 '원본'(반전 안 한) BGR 프레임에서 손을 찾아 Hand 목록으로 돌려줍니다 (없으면 빈 목록).

        label 은 사용자 실제 손 기준, landmarks 는 거울 미리보기 화면 기준 픽셀 좌표입니다.
        """
        # VIDEO 모드는 타임스탬프가 반드시 계속 증가해야 합니다.
        ts = max(int(timestamp_ms), self._last_ts + 1)
        self._last_ts = ts

        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)  # MediaPipe는 RGB를 기대함
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, ts)

        hands: list[Hand] = []
        for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
            top = handedness[0]
            hands.append(
                Hand(
                    label=top.category_name,
                    score=float(top.score),
                    landmarks=to_view_coords([(lm.x, lm.y) for lm in landmarks], w, h),
                )
            )
        return hands

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
