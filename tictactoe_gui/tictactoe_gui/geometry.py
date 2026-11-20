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
        raise ValueError('未知素材')
    asset=json.loads(files('tictactoe_motion.canvas').joinpath('illustrations',name+'.json').read_text())
    strokes=[[[.5+(u-.5)*width/(board_width-.002),
               .5+(v-.5)*(width/asset['aspect'])/(board_height-.002)] for u,v in stroke]
             for stroke in asset['strokes']]
    prepare_strokes(strokes, width=board_width, height=board_height, flip=flip)
    return {'name':name, 'width_mm':width*1000, 'strokes':strokes}


def validate_strokes(strokes):
    """! @brief Copy bounded normalized input without choosing a robot mapping."""
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 32:
        raise ValueError('需要 1–32 笔')
    if sum(len(s) if isinstance(s, list) else 10001 for s in strokes) > 8000:
        raise ValueError('总采样点不能超过 8000')
    result = []
    for number, stroke in enumerate(strokes, 1):
        if not isinstance(stroke, list) or not 2 <= len(stroke) <= 2000:
            raise ValueError(f'第 {number} 笔需要 2–2000 个点')
        row = []
        for point in stroke:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError('每个点必须包含 x、y')
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
                raise ValueError('坐标必须在画布内 [0,1]')
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
        raise ValueError('无效画布尺寸或方向')
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
            raise ValueError(f'第 {number} 笔太短，请画线而非单击')
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
        raise ValueError('轨迹过于复杂，请分多次执行')
    return result


def metric_distance(a, b, width, height):
    return math.hypot((a[0]-b[0])*width, (a[1]-b[1])*height)
