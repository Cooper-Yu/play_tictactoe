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
