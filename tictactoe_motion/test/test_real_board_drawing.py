"""Measured board geometry and physical pen-up ordering; no hardware launched."""
import copy
import math
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from tictactoe_motion.canvas.board_canvas import BoardCanvas
from tictactoe_motion.actions.drawing_actions import DrawingActions
from test_stroke_drawing import Driver


def profile():
    return yaml.safe_load((Path(__file__).parents[1]/'config/board_real.yaml').read_text())


def test_real_screen_corners_dimensions_and_axes():
    p = profile(); c = BoardCanvas(p)
    for uv, point in zip([(0,0),(1,0),(1,1),(0,1)], p['safe_corners']):
        assert c.metric_point(*uv) == pytest.approx(point)
    assert (c.x1-c.x0)*1000 == pytest.approx(138.003634761)
    assert (c.y1-c.y0)*1000 == pytest.approx(177.005239229)
    assert c.metric_point(.6,.5)[0] < c.metric_point(.5,.5)[0]
    assert c.metric_point(.5,.6)[1] > c.metric_point(.5,.5)[1]


def test_real_circle_remains_round_and_grid_bounded():
    a = DrawingActions(BoardCanvas(profile()))
    center = a.canvas.metric_point(.5,.5)
    circle = a._prepare(a.o_strokes(radius=.006)).paths[0]
    assert circle[0] == circle[-1]
    assert all(math.dist(p[:2],center[:2]) == pytest.approx(.006) for p in circle)
    assert len(a._prepare(a.grid_strokes(width=.06,height=.06)).paths) == 4
    with pytest.raises(ValueError): a.x_strokes(center=(.001,.001),size=.012)


def real_driver(fail_at=None):
    d = Driver(fail_at); d.actual.orientation.w = 0.; d.recording = SimpleNamespace(environment='real')
    d.actual.position.x = .2338; d.actual.position.y = .0069; d.actual.position.z = .206
    return d


def test_lift_precedes_lateral_transfer_and_x_finishes_hovering():
    d = real_driver(); a = DrawingActions(BoardCanvas(profile()),d)
    result = a.draw_x(size=.012)
    assert result['passed']
    first = d.calls[0][1].position
    assert (first.x,first.y,first.z) == pytest.approx((.2338,.0069,.216))
    assert d.calls[1][1].position.z == .216
    strokes = [value for kind,value in d.calls if kind == 'path']
    assert len(strokes) == 2
    assert all(p.position.z == pytest.approx(.206) for stroke in strokes for p in stroke)
    assert d.actual.position.z == .216


@pytest.mark.parametrize('fail_at',range(1,10))
def test_failure_never_advances_to_next_motion(fail_at):
    d = real_driver(fail_at)
    with pytest.raises(RuntimeError): DrawingActions(BoardCanvas(profile()),d).draw_x()
    assert len(d.calls) == fail_at


def test_wrong_driver_orientation_height_or_cancel_produces_no_motion():
    a = DrawingActions(BoardCanvas(profile()),Driver())
    with pytest.raises(ValueError): a.draw_x()
    d = real_driver(); d.actual.orientation.y=0.;d.actual.orientation.w=1.
    with pytest.raises(ValueError): DrawingActions(BoardCanvas(profile()),d).draw_x()
    assert not d.calls
    with pytest.raises(RuntimeError): DrawingActions(BoardCanvas(profile()),real_driver()).draw_x(cancelled=lambda:True)
    with pytest.raises(ValueError): DrawingActions(BoardCanvas(profile()),upper_z=.22,depth=.01).x_strokes()


@pytest.mark.parametrize('key,value',[
    ('canvas_axes','positive_x_negative_y'),('drawing_link6_z_m',.21),
    ('hover_link6_z_m',.206),('max_velocity_scaling',1.01),
    ('required_orientation_xyzw',[0,0,0,0]),('orientation_tolerance_rad',float('nan'))])
def test_incomplete_or_inconsistent_real_profile_rejected(key,value):
    p=copy.deepcopy(profile());p[key]=value
    with pytest.raises(ValueError): BoardCanvas(p)


def test_high_start_transfers_without_diagonal_descent():
    d=real_driver();d.actual.position.z=.23
    DrawingActions(BoardCanvas(profile()),d).draw_o(radius=.006)
    assert d.calls[0][1].position.z == .23
    assert d.calls[1][1].position.z == .216
    assert d.calls[0][1].position.x == d.calls[1][1].position.x
    assert d.calls[0][1].position.y == d.calls[1][1].position.y


@pytest.mark.parametrize('offset',[0.,.000002])
def test_resume_at_existing_approach_does_not_request_zero_length_plan(offset):
    d=real_driver();a=DrawingActions(BoardCanvas(profile()),d)
    path=a._prepare(a.x_strokes()).paths[0]
    d.actual.position.x=path[0][0]+offset
    d.actual.position.y=path[0][1]
    d.actual.position.z=.216
    result=a.draw_x()
    assert result['stages'][0]['result']['skipped'] is True
    assert d.calls[0][1].position.z == .206
    assert len([value for kind,value in d.calls if kind=='path']) == 2
    assert d.actual.position.z == .216


def test_approach_outside_noop_tolerance_still_moves_at_hover_height():
    d=real_driver();a=DrawingActions(BoardCanvas(profile()),d)
    path=a._prepare(a.x_strokes()).paths[0]
    d.actual.position.x=path[0][0]+.0001
    d.actual.position.y=path[0][1];d.actual.position.z=.216
    result=a.draw_x()
    assert not result['stages'][0]['result'].get('skipped',False)
    assert d.calls[0][1].position.z == .216


@pytest.mark.parametrize('name', ['smile', 'docker', 'chair'])
def test_illustrations_use_real_heights_and_preserve_separate_strokes(name):
    from tictactoe_motion.canvas.illustration_drawing import IllustrationDrawing
    d=real_driver();a=DrawingActions(BoardCanvas(profile()),d)
    drawing=IllustrationDrawing(a)
    result=drawing.draw(name,width=.05)
    assert result['passed'] and result['strokes'] > 1
    assert d.actual.position.z == pytest.approx(.216)
    assert all(stage['result']['passed'] for stage in result['stages'])
