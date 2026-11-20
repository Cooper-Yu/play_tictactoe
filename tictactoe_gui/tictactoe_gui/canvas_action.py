"""Map editable screen strokes onto the calibrated board without another ROS owner."""
import copy
from itertools import groupby
import math
from tictactoe_gui.geometry import prepare_strokes
from tictactoe_motion.canvas.canvas_drawing import CanvasDrawing


def continuous_line(parts, width, height):
    # Retain the original samples and require forward travel along one straight line.
    if len(parts) < 2:
        return None
    points = parts[0] + [point for part in parts[1:] for point in part[1:]]
    x0, y0 = points[0]
    dx = (points[-1][0]-x0)*width
    dy = (points[-1][1]-y0)*height
    length = math.hypot(dx, dy)
    if not .06 < length <= .120000001 or len(points) > 500:
        return None
    previous = 0.0
    for u, v in points:
        x, y = (u-x0)*width, (v-y0)*height
        along = (x*dx+y*dy)/length
        if along < previous-1e-9 or abs(x*dy-y*dx)/length > .00025:
            return None
        previous = along
    return points


class CanvasAction:
    """! @brief Validate all user strokes, then execute lifted batches in source order."""
    def __init__(self, canvas, strokes):
        if canvas.environment != 'real':
            raise ValueError('Real calibrated canvas required')
        self.input_count = len(strokes)
        width, height = canvas.x1-canvas.x0, canvas.y1-canvas.y0
        segmented = prepare_strokes(strokes, width=width, height=height, flip=False)
        self.prepared = []
        for source, items in groupby(segmented, key=lambda item: item['stroke']):
            items = list(items)
            parts = [item['points'] for item in items]
            line = continuous_line(parts, width, height)
            if line is None:
                self.prepared.extend(items)
            else:
                self.prepared.append(dict(stroke=source, part=1, points=line, fallback=parts))
        paths = [item['points'] for item in self.prepared]
        hover_z = canvas.profile.get('canvas_hover_link6_z_m', canvas.profile['hover_link6_z_m'])
        self.drawings = [CanvasDrawing(canvas, paths[i:i+32],
                           upper_z=hover_z, depth=hover_z-canvas.z,
                           snap=False, transfer_z=canvas.profile.get('transfer_link6_z_m'),
                           exit_to_transfer=i+32 >= len(paths),
                           fallback={j: item['fallback'] for j, item in
                                     enumerate(self.prepared[i:i+32], 1) if 'fallback' in item})
                         for i in range(0, len(paths), 32)]
        self.stages = []

    def run(self, driver, cancelled=lambda: False, on_stage=lambda state: None):
        """! @brief Preserve ordered progress and successful stages on cancellation/failure."""
        self.stages = []
        for index, drawing in enumerate(self.drawings, 1):
            def progress(stage):
                number = stage.split('_', 1)[0]
                batch_start = (index-1)*32
                if stage == 'exit_lift':
                    part_index = len(self.prepared)-1
                else:
                    part_index = batch_start+(int(number)-1 if number.isdigit() else 0)
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
        extra_parts = sum(stage.get('stage', '').endswith('_draw')
                          and '_fallback_' in stage['stage'] for stage in self.stages)
        replaced_parts = sum(stage.get('result', {}).get('fallback', False)
                             for stage in self.stages)
        return dict(motion_completed=True, ink_confirmed=None, shape='canvas',
                    input_strokes=self.input_count, strokes=len(self.prepared)+extra_parts-replaced_parts,
                    stages=copy.deepcopy(self.stages))
