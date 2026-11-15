"""Illustration scale, clipping, asset fidelity and no-motion failure checks."""
import math
from pathlib import Path
from unittest.mock import Mock
import pytest
import yaml
from tictactoe_motion.board_canvas import BoardCanvas
from tictactoe_motion.drawing_actions import DrawingActions
from tictactoe_motion.illustration_drawing import IllustrationDrawing


def illustration():
    profile = yaml.safe_load((Path(__file__).parents[1]/'config/board_sim.yaml').read_text())
    return IllustrationDrawing(DrawingActions(BoardCanvas(profile)))


@pytest.mark.parametrize('name', ['chair', 'docker', 'smile'])
def test_uniform_metric_scaling_and_rotation(name):
    drawing = illustration()
    for width in (.04, .06, .08):
        strokes = drawing.strokes(name, width=width)
        points = [p for s in strokes for p in s]
        xs = [p[0]*drawing.actions.width for p in points]
        assert math.isclose(max(xs)-min(xs), width, abs_tol=1e-6)
        turned = drawing.strokes(name, width=width, rotation=180)
        assert len(turned) == len(strokes)
        assert all(math.isclose(a[0]+b[0], 1, abs_tol=1e-12) and
                   math.isclose(a[1]+b[1], 1, abs_tol=1e-12)
                   for s,t in zip(strokes,turned) for a,b in zip(s,t))


@pytest.mark.parametrize('name', ['chair', 'docker', 'smile'])
def test_outside_and_nonfinite_fail_before_any_motion(name):
    drawing = illustration()
    drawing.actions.driver = Mock()
    with pytest.raises(ValueError):drawing.draw(name, center=(.99,.99))
    with pytest.raises(ValueError):drawing.draw(name, width=float('nan'))
    with pytest.raises(ValueError):drawing.draw(name, rotation=float('inf'))
    assert drawing.actions.driver.mock_calls == []


def test_named_assets_and_svg(tmp_path):
    drawing = illustration()
    with pytest.raises(ValueError):drawing.load('../chair')
    drawing.export_svg('chair', tmp_path/'chair.svg')
    assert '<polyline' in (tmp_path/'chair.svg').read_text()
    assert drawing.load('chair')['source'].endswith('512x512-1.png')
    assert len(drawing.load('docker')['strokes']) == 10
    assert drawing.load('smile')['stroke_layers'] == 2


def test_late_batch_invalid_is_rejected_before_motion():
    drawing = illustration();drawing.actions.driver = Mock()
    drawing.load = Mock(return_value={'aspect':1,'strokes':[[[.1,.1],[.2,.2]]]*33 + [[[5,5],[6,6]]]})
    with pytest.raises(ValueError):drawing.draw('chair')
    assert drawing.actions.driver.mock_calls == []
@pytest.mark.parametrize('anchor', [(357,128),(169,352),(186,331),(200,332)])
def test_chair_reported_gaps_are_covered(anchor):
    asset = illustration().load('chair')
    x0,y0,x1,y1 = asset['source_bounds_px']
    segments = [(a,b) for s in asset['strokes'] for a,b in zip(s,s[1:])]
    distances = []
    for a,b in segments:
        a = (x0+a[0]*(x1-x0), y0+a[1]*(y1-y0))
        b = (x0+b[0]*(x1-x0), y0+b[1]*(y1-y0))
        vector = (b[0]-a[0], b[1]-a[1])
        norm = vector[0]**2+vector[1]**2
        t = max(0,min(1,((anchor[0]-a[0])*vector[0]+(anchor[1]-a[1])*vector[1])/norm)) if norm else 0
        distances.append(math.dist(anchor,(a[0]+t*vector[0], a[1]+t*vector[1])))
    assert min(distances) < 2