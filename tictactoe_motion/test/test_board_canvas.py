"""Pure geometry and virtual reset tests; no simulation or robot is launched."""
import copy
import math
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
import yaml
from tictactoe_motion.board_canvas import BoardCanvas
from tictactoe_motion.canvas_drawing import CanvasDrawing
from tictactoe_motion.simulated_board import reset_gesture,write_ribbon
from test_stroke_drawing import Driver


def profile():return yaml.safe_load((Path(__file__).parents[1]/'config/board_sim.yaml').read_text())


def test_grid_corners_and_extent():
    p=profile();c=BoardCanvas(p)
    assert (c.nx+1,c.ny+1)==(289,387)
    assert c.point(0,0)==tuple(p['safe_corners'][0])
    assert c.point(c.nx,c.ny)==tuple(p['safe_corners'][2])
    for u,v in [(.13,.77),(.99,.001),(.5,.5)]:
        x,y,_=c.point(*c.index(u,v))
        expected=(c.x0+u*(c.x1-c.x0),c.y1-v*(c.y1-c.y0))
        assert math.dist((x,y),expected)<=math.hypot(c.step_x,c.step_y)/2+1e-12


@pytest.mark.parametrize('point',[(-.001,.5),(1.001,.5),(.5,float('nan')),(float('inf'),0)])
def test_outside_input_rejected_before_snap(point):
    with pytest.raises(ValueError):BoardCanvas(profile()).stroke([(0,0),point])


def test_grid_segments_remain_inside_and_small():
    c=BoardCanvas(profile());points=c.stroke([(.1,.2),(.9,.8)])
    assert len(points)>100
    assert all(c.x0<=x<=c.x1 and c.y0<=y<=c.y1 for x,y,z in points)
    assert max(math.dist(a,b) for a,b in zip(points,points[1:]))<=math.hypot(c.step_x,c.step_y)+1e-12


def test_quantization_cannot_create_false_stroke():
    with pytest.raises(ValueError):BoardCanvas(profile()).stroke([(.5,.5),(.50001,.50001)])


def test_smooth_circle_keeps_radius_and_closure():
    c=BoardCanvas(profile());radius=.01
    points=[(.5+radius/(c.x1-c.x0)*math.cos(2*math.pi*i/128),.5+radius/(c.y1-c.y0)*math.sin(2*math.pi*i/128)) for i in range(128)]
    points.append(points[0]);smooth=c.stroke(points,snap=False);grid=c.stroke(points)
    center=((c.x0+c.x1)/2,(c.y0+c.y1)/2)
    error=lambda pts:max(abs(math.dist(p[:2],center)-radius) for p in pts)
    assert error(smooth)<1e-12
    assert error(grid)>error(smooth)
    assert smooth[0]==smooth[-1]


def test_canvas_separate_strokes_use_lifted_transfer():
    c=BoardCanvas(profile());d=Driver();d.actual.position.x=.2
    def approach(pose):
        d.actual=copy.deepcopy(pose);d.calls.append(('pose',copy.deepcopy(pose)));return {'passed':True}
    d.pose=approach
    results=CanvasDrawing(c,[[(.4,.4),(.5,.5)],[(.4,.5),(.5,.4)]]).run(d)
    assert results[0]['stage']=='approach'
    assert [c[0] for c in d.calls].count('path')==2
    assert next(r for r in results if r['stage']=='2_transfer')['result']['passed']


def test_all_strokes_validated_before_motion():
    with pytest.raises(ValueError):CanvasDrawing(BoardCanvas(profile()),[[[.4,.4],[.5,.5]],[[2,.1],[.1,.1]]])


def test_reset_requires_downward_gesture_above_button():
    center=profile()['reset_center']
    sample=lambda z,x=center[0]:{'xyz':[x,center[1],z]}
    assert reset_gesture([sample(.25),sample(.245),sample(.24)],center)
    assert not reset_gesture([sample(.24),sample(.25)],center)
    assert not reset_gesture([sample(.25,x=.24),sample(.24,x=.24)],center)
    assert not reset_gesture([sample(.25),sample(.245)],center)


def test_ribbon_preserves_observed_xy_and_has_no_external_assets(tmp_path):
    path=tmp_path/'ink.dae';count=write_ribbon(path,[(.2,0),(.22,0)],.0274)
    root=ET.parse(path).getroot();ns={'c':root.tag.split('}')[0][1:]}
    vertices=list(map(float,root.find('.//c:float_array',ns).text.split()))
    assert count==2 and set(vertices[2::3])=={.0274}
    assert min(vertices[0::3])==.2 and max(vertices[0::3])==.22


def test_profile_rejects_tilt_and_wrong_environment():
    p=profile();p['safe_corners'][1][2]+=.01
    with pytest.raises(ValueError):BoardCanvas(p)
    p=copy.deepcopy(profile());p['environment']='real'
    with pytest.raises(ValueError):BoardCanvas(p)



def test_invalid_feedback_cannot_trigger_reset():
    center=profile()['reset_center']
    assert not reset_gesture([{'xyz':[center[0],center[1],.25]}, {'xyz':[float('nan'),center[1],.24]}],center)
