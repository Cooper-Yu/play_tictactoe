"""Reusable normalized pen-stroke assets with metric scaling and SVG export."""
import json
import math
from importlib.resources import files
from pathlib import Path
from tictactoe_motion.canvas_drawing import CanvasDrawing


class IllustrationDrawing:
    """! @brief Fit vector strokes on the board and execute lifted, validated batches.

    Assets contain normalized coordinates, aspect ratio and source provenance.
    Width is in meters; center is normalized board (u,v). Rotation is degrees.
    All batches are validated before the first movement. Simulation geometry
    and virtual Z levels remain explicitly supplied by the existing actions.
    """
    def __init__(self, actions):
        self.actions = actions

    def load(self, name):
        """! @brief Load a named bundled asset, without accepting filesystem paths."""
        if name not in ('chair', 'docker', 'smile'):
            raise ValueError('Unknown illustration')
        return json.loads(files('tictactoe_motion').joinpath('illustrations', name+'.json').read_text())

    def strokes(self, name, center=(.5, .5), width=.06, rotation=0):
        """! @brief Scale uniformly in metric space, rotate, and validate all paths."""
        asset = self.load(name)
        self.actions._center(center)
        self.actions._length(width)
        if not math.isfinite(rotation):
            raise ValueError('Rotation must be finite')
        angle = math.radians(rotation)
        height = width / asset['aspect']
        result = []
        for stroke in asset['strokes']:
            mapped = []
            for u, v in stroke:
                x, y = (u-.5)*width, (v-.5)*height
                mapped.append((center[0]+(x*math.cos(angle)-y*math.sin(angle))/self.actions.width,
                               center[1]+(x*math.sin(angle)+y*math.cos(angle))/self.actions.height))
            # Bound each execution path without reducing geometry or drawing connectors.
            part = [mapped[0]]
            length = 0
            for index, point in enumerate(mapped[1:], 1):
                distance = math.hypot((point[0]-part[-1][0])*self.actions.width,
                                      (point[1]-part[-1][1])*self.actions.height)
                if distance < 1e-9:
                    continue
                reversal = False
                if index >= 2:
                    before = mapped[index-2]
                    previous = mapped[index-1]
                    a = ((previous[0]-before[0])*self.actions.width, (previous[1]-before[1])*self.actions.height)
                    b = ((point[0]-previous[0])*self.actions.width, (point[1]-previous[1])*self.actions.height)
                    norm = math.hypot(*a)*math.hypot(*b)
                    reversal = norm > 1e-16 and (a[0]*b[0]+a[1]*b[1])/norm < -.5
                if reversal or length+distance > .08+1e-12 or len(part) >= 450:
                    if len(part) > 1:
                        result.append(part)
                    part = [part[-1]]
                    length = 0
                part.append(point)
                length += distance
            if len(part) > 1:
                result.append(part)
        self._batches(result)
        return result

    def _batches(self, strokes):
        if not 1 <= len(strokes) <= 256:
            raise ValueError('Illustration requires 1..256 strokes')
        return [CanvasDrawing(self.actions.canvas, strokes[i:i+32],
                              upper_z=self.actions.upper_z, depth=self.actions.depth, snap=False)
                for i in range(0, len(strokes), 32)]

    def draw(self, name, center=(.5, .5), width=.06, rotation=0,
             cancelled=lambda: False, on_stage=lambda stage: None):
        """! @brief Execute only after complete geometry validation; stop on any failure."""
        batches = self._batches(self.strokes(name, center, width, rotation))
        if self.actions.driver is None:
            raise RuntimeError('Drawing requires an explicit motion driver')
        stages = []
        for batch in batches:
            stages.extend(batch.run(self.actions.driver, cancelled, on_stage))
        return {'passed': True, 'strokes': sum(len(batch.paths) for batch in batches), 'stages': stages}

    def export_svg(self, name, destination):
        """! @brief Export source pen paths as resolution-independent black SVG lines."""
        asset = self.load(name)
        width, height = 1000, 1000/asset['aspect']
        paths = []
        for stroke in asset['strokes']:
            points = ' '.join(f'{u*width:.4f},{v*height:.4f}' for u, v in stroke)
            paths.append(f'<polyline points="{points}"/>')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 {width+20} {height+20}">'
               '<g fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               + ''.join(paths) + '</g></svg>')
        Path(destination).write_text(svg)