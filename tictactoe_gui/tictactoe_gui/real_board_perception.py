"""Map actual camera observations onto a measured real-board image quadrilateral."""
import cv2
import numpy as np
from tictactoe_gui.perception_preview import PerceptionPreview, _WIDTH, _HEIGHT


class RealBoardPerception(PerceptionPreview):
    """Use four measured grid intersections, ordered TL, TR, BR, BL."""
    def __init__(self, weights, image_points, *, device='cpu', nine_weights=None):
        super().__init__(weights, device)
        points = np.asarray(image_points, dtype=np.float32)
        if points.shape != (4, 2) or not np.isfinite(points).all():
            raise ValueError('Require four finite image intersections')
        if not cv2.isContourConvex(points.astype(np.int32)) or abs(cv2.contourArea(points)) < 25:
            raise ValueError('Grid intersections must form a convex quadrilateral')
        target = np.float32([[_WIDTH/3, _HEIGHT/3], [2*_WIDTH/3, _HEIGHT/3],
                             [2*_WIDTH/3, 2*_HEIGHT/3], [_WIDTH/3, 2*_HEIGHT/3]])
        self.transform = cv2.getPerspectiveTransform(points, target)
        self.shape = None
        self.nine_preview = PerceptionPreview(nine_weights, device) if nine_weights else None
        if self.nine_preview is not None and not self.nine_preview.weights.is_file():
            raise ValueError('9x9 YOLO weights are missing')

    def _detect(self, raw, transform, size):
        if size == 9 and self.nine_preview is not None:
            return self.nine_preview._detect(raw, transform, size)
        return super()._detect(raw, transform, size)

    def _camera_frame(self, image):
        raw = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if raw is None:
            raise ValueError('Could not decode real camera frame')
        if self.shape is None:
            self.shape = raw.shape
        if raw.shape != self.shape:
            raise ValueError('Camera resolution changed; recalibrate the grid')
        return raw, self.transform
