"""Map editable screen strokes onto the calibrated board without another ROS owner."""
import copy
from tictactoe_gui.geometry import prepare_strokes
from tictactoe_motion.canvas_drawing import CanvasDrawing


class CanvasAction:
    """! @brief Validate all user strokes, then execute lifted batches in source order."""
    def __init__(self, canvas, strokes):
        if canvas.environment != 'real':
            raise ValueError('Real calibrated canvas required')
        self.input_count = len(strokes)
        self.prepared = prepare_strokes(strokes, width=canvas.x1-canvas.x0,
                                        height=canvas.y1-canvas.y0, flip=False)
        paths = [item['points'] for item in self.prepared]
        self.drawings = [CanvasDrawing(canvas, paths[i:i+32],
                           upper_z=canvas.profile['hover_link6_z_m'],
                           depth=canvas.profile['hover_link6_z_m']-canvas.z,
                           snap=False) for i in range(0, len(paths), 32)]
        self.stages = []

    def run(self, driver, cancelled=lambda: False, on_stage=lambda state: None):
        """! @brief Preserve ordered progress and successful stages on cancellation/failure."""
        self.stages = []
        for index, drawing in enumerate(self.drawings, 1):
            def progress(stage):
                number = stage.split('_', 1)[0]
                part_index = (index-1)*32+(int(number)-1 if number.isdigit() else 0)
                source = self.prepared[part_index]['stroke']
                on_stage(dict(shape='canvas', batch=index, batches=len(self.drawings),
                              stage=stage, completed_stages=len(self.stages)+len(drawing.results),
                              source_stroke=source, completed_input_strokes=source-1,
                              completed_parts=part_index, total_parts=len(self.prepared),
                              total_input_strokes=self.input_count))
            try:
                self.stages.extend(drawing.run(driver, cancelled=cancelled, on_stage=progress))
            except BaseException:
                self.stages.extend(copy.deepcopy(drawing.results))
                raise
        return dict(motion_completed=True, ink_confirmed=None, shape='canvas',
                    input_strokes=self.input_count, strokes=len(self.prepared),
                    stages=copy.deepcopy(self.stages))
