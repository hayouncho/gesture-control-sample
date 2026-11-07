"""MediaPipe 손 인식 모델(hand_landmarker.task)을 models/ 폴더에 내려받습니다.

실행: python download_model.py
이미 파일이 있으면 다시 받지 않습니다.
"""
from pathlib import Path
import urllib.request

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)
MODEL_PATH = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"


def main() -> None:
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 0:
        print(f"이미 있습니다: {MODEL_PATH}")
        return
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"내려받는 중: {MODEL_URL}")
    tmp = MODEL_PATH.with_suffix(".part")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    tmp.replace(MODEL_PATH)
    print(f"완료: {MODEL_PATH} ({MODEL_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
