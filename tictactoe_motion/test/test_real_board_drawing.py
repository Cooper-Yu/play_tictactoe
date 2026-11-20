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
    d.scaling = dict(velocity_scaling=.45, acceleration_scaling=.45)
    d.node = SimpleNamespace(
        cartesian_planner=SimpleNamespace(canvas_native_timing=False),
        get_parameter=lambda key: SimpleNamespace(value=d.scaling[key]))
    d.parameters = lambda **values: d.scaling.update(values)
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


@pytest.mark.parametrize('shape', ['x', 'o'])
def test_real_contact_speed_is_separate_from_pen_and_travel_speed(shape):
    d = real_driver()
    observed = []
    original_path, original_linear = d.path, d.linear
    def path(poses, **options):
        observed.append(('draw', dict(d.scaling), d.node.cartesian_planner.canvas_native_timing))
        return original_path(poses, **options)
    def linear(point, **options):
        observed.append(('move', dict(d.scaling), d.node.cartesian_planner.canvas_native_timing))
        return original_linear(point, **options)
    d.path, d.linear = path, linear
    actions = DrawingActions(BoardCanvas(profile()), d)
    getattr(actions, 'draw_'+shape)()
    assert all(value == dict(velocity_scaling=.45, acceleration_scaling=.45)
               for kind, value, native in observed if kind == 'draw')
    assert all(value == dict(velocity_scaling=1., acceleration_scaling=1.)
               for kind, value, native in observed if kind == 'move')
    assert all(native for _, _, native in observed)
    assert d.scaling == dict(velocity_scaling=.45, acceleration_scaling=.45)
    assert d.node.cartesian_planner.canvas_native_timing is False


@pytest.mark.parametrize('key,value', [
    ('travel_velocity_scaling', 0), ('pen_vertical_velocity_scaling', 1.01),
    ('travel_velocity_scaling', float('nan')), ('pen_vertical_velocity_scaling', True)])
def test_invalid_phase_scaling_is_rejected_before_motion(key, value):
    p = profile(); p[key] = value
    with pytest.raises(ValueError, match='phase scaling'):
        BoardCanvas(p)


@pytest.mark.parametrize('value', [.49, .71, float('nan'), float('inf'), True, '0.7'])
def test_invalid_transfer_excursion_rejected_before_motion(value):
    p = profile(); p['transfer_joint_excursion_rad'] = value
    with pytest.raises(ValueError, match='Transfer joint excursion'):
        BoardCanvas(p)


def test_only_horizontal_pen_up_moves_use_relaxed_limit():
    d = real_driver(); observed = []; stage = ['']
    original = d.linear
    def linear(point, **options):
        observed.append((stage[0], d.actual.position.z, point.z,
                         options.get('excursion_limit', .5)))
        return original(point, **options)
    d.linear = linear
    a = DrawingActions(BoardCanvas(profile()), d)
    a.draw_x(on_stage=lambda name: stage.__setitem__(0, name))
    assert any(name == '2_transfer' for name, *_ in observed)
    for name, start_z, end_z, limit in observed:
        if name in ('approach', '2_transfer'):
            assert limit == .7
            assert start_z == pytest.approx(end_z)
            assert start_z >= .211
        else:
            assert limit == .5


def test_relaxed_transfer_rejection_keeps_segmented_fallback():
    from geometry_msgs.msg import Point
    from tictactoe_motion.canvas.canvas_drawing import CanvasDrawing
    calls = []
    class TransferDriver:
        def linear(self, point, **options):
            calls.append((copy.deepcopy(point), options))
            return None if options.get('allow_excursion_retry') else {'passed': True}
    start = Point(x=.12, y=-.1, z=.216)
    end = Point(x=.12, y=.03, z=.216)
    result = CanvasDrawing.real_approach(TransferDriver(), start, end, lambda: False,
                                        excursion_limit=.7)
    assert result['approach_segments'] == 3
    assert calls[0][1]['excursion_limit'] == .7
    assert all(options.get('excursion_limit', .5) == .5 for _, options in calls[1:])
    assert calls[-1][0] == end
    with pytest.raises(ValueError, match='horizontal'):
        CanvasDrawing.real_approach(TransferDriver(), start, Point(x=.12,y=.03,z=.211),
                                    lambda: False, excursion_limit=.7)
