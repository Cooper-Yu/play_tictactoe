"""Verify pen-up transfers, closed circle, and failure/cancellation boundaries."""
import copy
import math
import pytest
from geometry_msgs.msg import Pose
from tictactoe_motion.actions.stroke_drawing import StrokeDrawing


class Driver:
    def __init__(self, fail_at=None):
        self.actual=Pose(); self.actual.position.z=.25; self.actual.orientation.y=1.
        self.calls=[]; self.fail_at=fail_at
    def current_pose(self): return copy.deepcopy(self.actual)
    def linear(self, point, *, speed=None, allow_excursion_retry=False, excursion_limit=.5):
        self.actual.position=copy.deepcopy(point)
        self.calls.append(('linear',self.current_pose()))
        return {'passed':len(self.calls)!=self.fail_at}
    def path(self, poses, excursion_limit=0.5, *, speed=None, allow_plan_retry=False):
        self.calls.append(('path',copy.deepcopy(poses)))
        self.actual=copy.deepcopy(poses[-1])
        return {'passed':len(self.calls)!=self.fail_at}


def test_cross_has_no_diagonal_transfer_at_drawing_height():
    d=Driver(); sequence=StrokeDrawing('cross'); results=sequence.run(d)
    assert [r['stage'] for r in results]==['1_lower','1_draw','1_lift','2_transfer','2_lower','2_draw','2_lift']
    assert [call[0] for call in d.calls]==['linear','path','linear','linear','linear','path','linear']
    assert d.calls[2][1].position.z==.25
    assert d.calls[3][1].position.z==.25
    assert d.calls[3][1].position.x==0
    assert d.calls[3][1].position.y==.02
    for stroke in sequence.strokes:
        assert len(stroke)==2
        assert all(p.position.z==.24 and p.orientation.y==1 for p in stroke)
    assert d.actual.position.z==.25


def test_circle_is_closed_and_lifts_only_after_full_path():
    d=Driver(); sequence=StrokeDrawing('circle'); sequence.run(d)
    assert [c[0] for c in d.calls]==['linear','path','linear']
    stroke=d.calls[1][1]
    assert stroke[0]==stroke[-1]
    assert len(stroke)==65
    assert all(math.isclose(math.hypot(p.position.x-.01,p.position.y),.01) for p in stroke)
    assert d.actual.position.z==.25


@pytest.mark.parametrize('fail_at',range(1,8))
def test_failed_stage_never_requests_next_motion(fail_at):
    d=Driver(fail_at)
    with pytest.raises(RuntimeError,match='failed verification'): StrokeDrawing('cross').run(d)
    assert len(d.calls)==fail_at


@pytest.mark.parametrize('stop_after',range(7))
def test_cancellation_never_requests_next_motion(stop_after):
    d=Driver()
    with pytest.raises(RuntimeError,match='cancelled'):
        StrokeDrawing('cross').run(d,cancelled=lambda:len(d.calls)>=stop_after)
    assert len(d.calls)==stop_after


@pytest.mark.parametrize('depth',[0,-.01,float('nan'),float('inf'),.051])
def test_invalid_depth_rejected(depth):
    with pytest.raises(ValueError): StrokeDrawing('cross',depth=depth)
