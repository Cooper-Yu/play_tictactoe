"""Pure path checks: X diagonals, explicit transfer and closed O at fixed tool pose."""
import copy
import math
import pytest
from geometry_msgs.msg import Pose
from tictactoe_motion.drawing_paths import cross_path, circle_path
from tictactoe_motion.cartesian_planner import xyz


def start():
    p=Pose();p.position.x=.2;p.position.y=-.1;p.position.z=.21;p.orientation.y=1.
    return p


def test_cross_strokes_and_transfer_preserve_input():
    p=start();before=copy.deepcopy(p);points=cross_path(p,.02)
    assert p==before and len(points)==4
    assert xyz(points[1])==pytest.approx((.22,-.08,.21))
    assert xyz(points[2])==pytest.approx((.2,-.08,.21))
    assert xyz(points[3])==pytest.approx((.22,-.1,.21))
    assert all(v.orientation==p.orientation for v in points)


def test_circle_closed_constant_radius_and_height():
    p=start();points=circle_path(p,.01)
    assert points[0]==points[-1] and len(points)==65
    assert len({(round(v.position.x,8),round(v.position.y,8)) for v in points})==64
    for v in points:
        assert math.hypot(v.position.x-.21,v.position.y+.1)==pytest.approx(.01)
        assert v.position.z==p.position.z and v.orientation==p.orientation


@pytest.mark.parametrize('value',[0.,-.01,float('nan'),float('inf'),1.])
def test_invalid_dimensions_rejected(value):
    with pytest.raises(ValueError):cross_path(start(),value)
    with pytest.raises(ValueError):circle_path(start(),value)
