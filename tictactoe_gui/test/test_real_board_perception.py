import cv2
import numpy as np
from tictactoe_gui.real_board_perception import RealBoardPerception


def test_internal_grid_maps_in_camera_order():
    points = [[110, 80], [190, 80], [200, 150], [100, 150]]
    detector = RealBoardPerception('unused.pt', points)
    actual = cv2.perspectiveTransform(np.float32([points]), detector.transform)[0]
    assert np.allclose(actual, [[140, 189], [280, 189], [280, 378], [140, 378]])


def test_invalid_intersections_rejected():
    import pytest
    with pytest.raises(ValueError):
        RealBoardPerception('unused.pt', [[0, 0]] * 4)


def test_camera_overlay_preserves_perspective_and_confidence(monkeypatch):
    from tictactoe_gui.perception_preview import PerceptionPreview
    raw = np.zeros((80, 100, 3), dtype=np.uint8)
    transform = np.float64([[2, 0, 10], [0, 2, 20], [0, 0, 1]])
    polygon = np.float32([[50,80], [110,80], [110,140], [50,140]])
    preview = PerceptionPreview()
    preview._detect = lambda *args: {(0,0): {'X': (.86, polygon)}}
    rectangles, labels = [], []
    rectangle, put_text = cv2.rectangle, cv2.putText
    def capture_rectangle(image, start, end, color, thickness, *args):
        rectangles.append((tuple(start), tuple(end), thickness))
        return rectangle(image, start, end, color, thickness, *args)
    def capture_text(image, text, *args):
        labels.append(text)
        return put_text(image, text, *args)
    monkeypatch.setattr(cv2, 'rectangle', capture_rectangle)
    monkeypatch.setattr(cv2, 'putText', capture_text)
    output = preview.camera_overlay(raw, transform, 3)
    assert output.shape == raw.shape
    assert ((20,30), (50,60), 1) in rectangles
    assert labels == ['X 0.86']
    assert not raw.any()
    assert output.any()
