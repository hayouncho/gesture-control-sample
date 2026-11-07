"""1단계 확인용: 웹캠 + MediaPipe 손 인식만 실행합니다 (제스처 판별·유튜브 제어 없음).

실행: python step1_hand_check.py
종료: 미리보기 창을 클릭한 뒤 q 또는 ESC / 창 닫기(X) / 터미널에서 Ctrl+C
"""
import time

import cv2

from gesture_control import config
from gesture_control.camera import Camera, mirror_view
from gesture_control.hand_tracker import HandTracker
from gesture_control.overlay import GRAY, GREEN, RED, draw_hand, draw_lines


def main() -> None:
    print("1단계: 웹캠과 손 인식 확인. 종료: 창에서 q/ESC 또는 터미널에서 Ctrl+C")
    with Camera(config.CAMERA_INDEX, config.FRAME_WIDTH, config.FRAME_HEIGHT) as cam, \
         HandTracker(config.MODEL_PATH, config.NUM_HANDS) as tracker:
        fps, last = 0.0, time.monotonic()
        try:
            while True:
                raw = cam.read()                               # 카메라 원본
                if raw is None:
                    print("프레임을 읽지 못했습니다. 웹캠 연결을 확인하세요.")
                    break
                now = time.monotonic()
                hands = tracker.detect(raw, int(now * 1000))   # 원본으로 인식 -> Left/Right = 실제 손
                frame = mirror_view(raw)                       # 미리보기만 거울 화면

                fps = 0.9 * fps + 0.1 * (1.0 / max(now - last, 1e-6))
                last = now
                for hand in hands:
                    draw_hand(frame, hand)
                status = f"hands: {len(hands)}" if hands else "NO HAND"
                draw_lines(frame, [(f"FPS {fps:4.1f}", GRAY), (status, GREEN if hands else RED),
                                   ("q / ESC: quit", GRAY)])

                cv2.imshow(config.WINDOW_NAME, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if cv2.getWindowProperty(config.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            cv2.destroyAllWindows()
    print("종료했습니다.")


if __name__ == "__main__":
    main()
