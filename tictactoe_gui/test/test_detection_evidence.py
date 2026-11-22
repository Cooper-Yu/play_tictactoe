"""Keep numeric confidence and cell evidence from the exact observation call."""
import threading
import numpy as np
from tictactoe_gui.perception_preview import PerceptionPreview


def test_observation_records_confidence_without_changing_cell_decision():
    preview = PerceptionPreview.__new__(PerceptionPreview)
    preview.lock = threading.Lock()
    preview._camera_frame = lambda image: (None, None)
    polygon = np.array([[1,2],[3,2],[3,4],[1,4]],dtype=np.int32)
    preview._detect = lambda *args: {(0,8):{'X':(.42,polygon),'O':(.31,polygon)}}
    assert preview.detect_cells(b'frame',9) == {(0,8):frozenset(('X','O'))}
    assert preview.last_detection_details == [
        dict(row=1,column=9,mark='X',confidence=.42,rectified_polygon=polygon.tolist()),
        dict(row=1,column=9,mark='O',confidence=.31,rectified_polygon=polygon.tolist())]
    preview._detect = lambda *args: {}
    assert preview.detect_cells(b'next-frame',9) == {}
    assert preview.last_detection_details == []
