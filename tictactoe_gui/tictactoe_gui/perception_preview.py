"""Read-only image diagnostics for the fixed Gazebo game camera."""
from math import cos, sin, tan
from pathlib import Path
import threading

import cv2
import numpy as np

from tictactoe_perception.stable_player_move import StablePlayerMove as StablePlayerMove


# Default tictactoe.world camera and the inset rectangle drawn by GameCoordinator.
# List corners clockwise from the camera's top left.
_WIDTH, _HEIGHT = 420, 567
_CAMERA = np.array([0.198395, 0.199552, 0.203527])
_PITCH, _YAW, _HFOV = 0.785379, -1.57, 1.3962634
_BOARD = np.array([[x, y, 0.0274] for x, y in (
    (0.270, -0.0855), (0.130, -0.0855), (0.130, 0.1035), (0.270, 0.1035)
)])
_VIEWS = ("rectified", "edges", "detections")


def board_transform(width, height):
    """Map camera pixels to the projected playing area with the camera's orientation."""
    cp, sp, cy, sy = cos(_PITCH), sin(_PITCH), cos(_YAW), sin(_YAW)
    rotation = np.array([[cy*cp, -sy, cy*sp], [sy*cp, cy, sy*sp], [-sp, 0, cp]])
    direction = (_BOARD - _CAMERA) @ rotation
    focal = width / (2 * tan(_HFOV / 2))
    source = -direction[:, 1:] / direction[:, :1] * focal + [width/2, height/2]
    target = [[0, 0], [_WIDTH-1, 0], [_WIDTH-1, _HEIGHT-1], [0, _HEIGHT-1]]
    return cv2.getPerspectiveTransform(source.astype(np.float32), np.float32(target))


class PerceptionPreview:
    """Cache the latest result for each view and serialize model access."""
    def __init__(self, weights="", device="cpu"):
        self.weights = Path(weights).expanduser() if weights else None
        self.device = device
        self.model = None
        self.lock = threading.Lock()
        self.cache = {}

    def render(self, image, sequence, size, view):
        if view not in _VIEWS:
            raise ValueError("未知预览模式")
        if size not in (3, 9):
            raise ValueError("不支持的棋盘大小")
        if not self.lock.acquire(blocking=False):
            return None
        try:
            key = (sequence, size)
            previous = self.cache.get(view)
            if previous is not None and previous[0] == key:
                return previous[1]
            raw, transform = self._camera_frame(image)
            rectified = cv2.warpPerspective(raw, transform, (_WIDTH, _HEIGHT))
            if view == "edges":
                gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
                output = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 24, 64)
            elif view == "detections":
                output = self.overlay(raw, rectified, transform, size)
            else:
                output = rectified
            ok, encoded = cv2.imencode(".jpg", output)
            if not ok:
                raise RuntimeError("无法生成预览图像")
            result = encoded.tobytes()
            self.cache[view] = (key, result)
            return result
        finally:
            self.lock.release()

    @staticmethod
    def _camera_frame(image):
        raw = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if raw is None:
            raise RuntimeError("相机图像解码失败")
        height, width = raw.shape[:2]
        if abs(width / height - 16 / 9) > .02:
            raise RuntimeError("图像尺寸与当前仿真相机标定不匹配")
        return raw, board_transform(width, height)

    def detect_cells(self, image, size=3):
        """Return all detected mark classes per cell, including conflicts."""
        if size not in (3, 9):
            raise ValueError("不支持的棋盘大小")
        with self.lock:
            raw, transform = self._camera_frame(image)
            return {cell: frozenset(candidates)
                    for cell, candidates in self._detect(raw, transform, size).items()}

    def _detect(self, raw, transform, size):
        if self.model is None:
            if self.weights is None or not self.weights.is_file():
                raise RuntimeError("尚未配置 YOLO 权重")
            from ultralytics import YOLO
            self.model = YOLO(str(self.weights))
        # Keep the original perspective for inference. Each zone owns only its
        # share of the board, even though its crop includes neighboring cells.
        zones = [(0, 0, size, size)] if size == 3 else [
            (r0, c0, r1, c1) for r0, r1 in ((0, 5), (5, 9))
            for c0, c1 in ((0, 5), (5, 9))
        ]
        inverse = np.linalg.inv(transform)
        inputs, offsets = [], []
        height, width = raw.shape[:2]
        for r0, c0, r1, c1 in zones:
            if size == 3:
                inputs.append(raw)
                offsets.append((0, 0))
                continue
            x0, x1 = (c0-1)*_WIDTH/size, (c1+1)*_WIDTH/size
            y0, y1 = (r0-1)*_HEIGHT/size, (r1+1)*_HEIGHT/size
            corners = np.float32([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]])
            pixels = cv2.perspectiveTransform(corners, inverse)[0]
            left, top = np.maximum(np.floor(pixels.min(axis=0)).astype(int), 0)
            right, bottom = np.minimum(np.ceil(pixels.max(axis=0)).astype(int), [width, height])
            inputs.append(raw[top:bottom, left:right])
            offsets.append((left, top))

        results = self.model.predict(inputs, imgsz=640, rect=False, end2end=False,
                                     conf=.25, iou=.7, device=self.device, verbose=False)
        occupied = {}
        for result, (left, top), (r0, c0, r1, c1) in zip(results, offsets, zones):
            for x0, y0, x1, y1, confidence, category in result.boxes.data.cpu().tolist():
                corners = np.float32([[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]])
                corners += np.float32([left, top])
                center = corners.mean(axis=1).reshape(1, 1, 2)
                x, y = cv2.perspectiveTransform(center, transform)[0, 0]
                row, col = int(np.floor(y*size/_HEIGHT)), int(np.floor(x*size/_WIDTH))
                mark = result.names[int(category)].upper()
                if r0 <= row < r1 and c0 <= col < c1 and mark in ("X", "O"):
                    polygon = cv2.perspectiveTransform(corners, transform)[0]
                    candidates = occupied.setdefault((row, col), {})
                    if mark not in candidates or confidence > candidates[mark][0]:
                        candidates[mark] = (confidence, np.rint(polygon).astype(np.int32))

        return occupied

    def overlay(self, raw, output, transform, size):
        occupied = self._detect(raw, transform, size)
        for index in range(1, size):
            u, v = round(index*_WIDTH/size), round(index*_HEIGHT/size)
            cv2.line(output, (u, 0), (u, _HEIGHT-1), (155, 112, 58), 1)
            cv2.line(output, (0, v), (_WIDTH-1, v), (155, 112, 58), 1)
        for (row, col), candidates in occupied.items():
            for mark, (_, polygon) in candidates.items():
                color = (208, 240, 117) if mark == "X" else (94, 191, 255)
                cv2.polylines(output, [polygon], True, color, 2, cv2.LINE_AA)
            label = "/".join(sorted(candidates)) + f" {row+1},{col+1}"
            anchor = (round(col*_WIDTH/size)+3, round(row*_HEIGHT/size)+15)
            cv2.putText(output, label, anchor, cv2.FONT_HERSHEY_SIMPLEX,
                        .42, (240, 255, 255), 1, cv2.LINE_AA)
        return output
