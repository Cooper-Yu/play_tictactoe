"""Validate tablet strokes independently of ROS and preserve their order."""
import math
import json
from importlib.resources import files


def load_illustration(name, width=.06, *, board_width=.144, board_height=.193, flip=True):
    """! @brief Fit one bundled vector asset onto the editable tablet preview.

    The inverse screen map exactly reproduces the existing 60-mm/180-degree
    simulation illustration mapping after prepare_strokes is applied.
    """
    if name not in ('chair', 'docker', 'smile'):
        raise ValueError('Unknown asset')
    asset=json.loads(files('tictactoe_motion.canvas').joinpath('illustrations',name+'.json').read_text())
    strokes=[[[.5+(u-.5)*width/(board_width-.002),
               .5+(v-.5)*(width/asset['aspect'])/(board_height-.002)] for u,v in stroke]
             for stroke in asset['strokes']]
    prepare_strokes(strokes, width=board_width, height=board_height, flip=flip)
    return {'name':name, 'width_mm':width*1000, 'strokes':strokes}


def validate_strokes(strokes):
    """! @brief Copy bounded normalized input without choosing a robot mapping."""
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 32:
        raise ValueError('requires 1–32 strokes')
    if sum(len(s) if isinstance(s, list) else 10001 for s in strokes) > 8000:
        raise ValueError('Total sample count must not exceed 8000')
    result = []
    for number, stroke in enumerate(strokes, 1):
        if not isinstance(stroke, list) or not 2 <= len(stroke) <= 2000:
            raise ValueError(f'Stroke {number} requires 2–2000 points')
        row = []
        for point in stroke:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError('Each point must contain x, y')
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
                raise ValueError('Coordinates must be within the canvas [0,1]')
            row.append([float(v) for v in point])
        result.append(row)
    return result


def prepare_strokes(strokes, width=.144, height=.193, *, flip=True):
    """! @brief Map screen points to board coordinates and split bounded subpaths.

    Input is 1..32 screen-space strokes of normalized [x,y] coordinates.
    The legacy simulation map defaults to 180 degrees; real board input uses
    flip=False and the measured physical width/height.
    No smoothing changes the user's curve; only duplicate submicron samples
    are removed. Long paths or sharp reversals receive explicit lifted splits.
    """
    strokes = validate_strokes(strokes)
    if (any(isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v <= .002 for v in (width, height))
            or not isinstance(flip, bool)):
        raise ValueError('Invalid canvas dimensions or orientation')
    result = []
    for number, stroke in enumerate(strokes, 1):
        points = []
        for point in stroke:
            # Leave room for the fixed-width pen at every screen edge.
            mapped = [.001/width+point[0]*(1-.002/width),
                      .001/height+point[1]*(1-.002/height)]
            if flip:
                mapped = [1-mapped[0], 1-mapped[1]]
            if not points:
                points.append(mapped)
            elif metric_distance(mapped, points[-1], width, height) >= .00001:
                previous = points[-1]
                count = math.ceil(metric_distance(mapped, previous, width, height)/.01)
                points.extend([[previous[0]+(mapped[0]-previous[0])*i/count,
                                previous[1]+(mapped[1]-previous[1])*i/count]
                               for i in range(1, count+1)])
        if len(points) < 2:
            raise ValueError(f'Stroke {number} is too short, Draw a line instead of clicking')
        part, length, part_number = [points[0]], 0.0, 1
        for point in points[1:]:
            distance = metric_distance(part[-1], point, width, height)
            reversal = False
            if len(part) >= 2:
                a = [(part[-1][0]-part[-2][0])*width, (part[-1][1]-part[-2][1])*height]
                b = [(point[0]-part[-1][0])*width, (point[1]-part[-1][1])*height]
                reversal = sum(x*y for x, y in zip(a, b)) < -.5*math.hypot(*a)*math.hypot(*b)
            if len(part) > 1 and (length+distance > .06 or len(part) >= 350 or reversal):
                result.append({'stroke': number, 'part': part_number, 'points': part})
                part, length, part_number = [part[-1]], 0.0, part_number+1
            # A single long segment is interpolated by the existing Cartesian planner.
            part.append(point)
            length += distance
        if len(part) > 1:
            result.append({'stroke': number, 'part': part_number, 'points': part})
    if len(result) > 256:
        raise ValueError('Trajectory is too complex, Split this into separate executions')
    return result


def metric_distance(a, b, width, height):
    return math.hypot((a[0]-b[0])*width, (a[1]-b[1])*height)


def prepare_game_strokes(strokes, width=.144, height=.193):
    """Map the playable grid preview to the inset simulation board, preserving strokes."""
    prepared = prepare_strokes(strokes, width=width-.004, height=height-.004)
    for part in prepared:
        # The grid already has a 2 mm outer inset. Undo the standalone canvas's
        # extra 1 mm inset so mouse coordinates and camera cell boundaries agree.
        part['points'] = [[.5+((u-.001/(width-.004))/(1-.002/(width-.004))-.5)
                           *(width-.004)/width,
                           .5+((v-.001/(height-.004))/(1-.002/(height-.004))-.5)
                           *(height-.004)/height] for u, v in part['points']]
    return prepared


def verify_handwriting_cell(strokes, found, size):
    """Reject cross-cell ink even if the detector found only one of its fragments."""
    row, col, _ = found
    if any(not (col/size <= u <= (col+1)/size and row/size <= v <= (row+1)/size)
           for stroke in strokes for u, v in stroke):
        raise RuntimeError('Handwriting crosses a cell boundary; inspect and clear the board')


def verify_handwriting_shape(strokes, width=.140, height=.189):
    """Veto obvious closed polygons; camera consistency alone cannot reject false positives.

    This narrow veto does not classify X/O or replace YOLO. Curved, open and
    multi-stroke symbols still require the camera's existing recognition gate.
    """
    import cv2
    import numpy as np
    for stroke in strokes:
        points = np.asarray([[u*width, v*height] for u, v in stroke], dtype=np.float32)
        extent = float(np.linalg.norm(np.ptp(points, axis=0)))
        if extent < .002 or float(np.linalg.norm(points[0]-points[-1])) > extent*.12:
            continue
        perimeter = cv2.arcLength(points, True)
        corners = cv2.approxPolyDP(points, perimeter*.035, True)
        if len(corners) in (3, 4) and cv2.isContourConvex(corners):
            raise RuntimeError('Handwriting forms a closed polygon, not an accepted X/O; inspect and clear the board')
