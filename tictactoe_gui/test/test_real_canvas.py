"""Calibrated canvas mapping and protected shared-workstation entry points."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path
import pytest
import yaml
from tictactoe_gui.geometry import prepare_strokes, load_illustration
from tictactoe_gui.workbench import WorkbenchSession, make_handler, validate_command
from tictactoe_gui.cloud_gateway import make_gateway
from tictactoe_gui.canvas_action import CanvasAction
from tictactoe_motion.canvas.board_canvas import BoardCanvas


def board():
    profile = yaml.safe_load((Path(__file__).parents[2]/'tictactoe_motion/config/board_real.yaml').read_text())
    return BoardCanvas(profile)


def test_real_mapping_margin_and_source_order():
    parts = prepare_strokes([[[0,0],[1,0]], [[.5,.5],[.5,.6]]], .138, .177, flip=False)
    assert parts[0]['points'][0] == pytest.approx([.001/.138,.001/.177])
    assert parts[-2]['points'][-1][0] == pytest.approx(1-.001/.138)
    assert [p['stroke'] for p in parts] == sorted(p['stroke'] for p in parts)
    assert parts[-1]['stroke'] == 2
    assert all(a['points'][-1] == b['points'][0] for a,b in zip(parts,parts[1:]) if a['stroke']==b['stroke'])


@pytest.mark.parametrize('name', ['smile','docker','chair'])
def test_real_asset_preserves_metric_width(name):
    asset = load_illustration(name, board_width=.138, board_height=.177, flip=False)
    parts = prepare_strokes(asset['strokes'], .138, .177, flip=False)
    values = [p[0]*.138 for part in parts for p in part['points']]
    assert max(values)-min(values) == pytest.approx(.06, abs=.00001)


def test_all_geometry_checked_before_driver_is_used(monkeypatch):
    import tictactoe_gui.canvas_action as module
    created=[]
    class Batch:
        def __init__(self, canvas, paths, **kwargs):
            created.append(paths)
            self.results=[]
        def run(self, driver, cancelled, on_stage):
            self.results=[]
            if cancelled(): raise RuntimeError('cancelled')
            on_stage('1_draw'); self.results=[{'passed':True}]; return self.results
    monkeypatch.setattr(module, 'CanvasDrawing', Batch)
    strokes=[[[0,i/32],[1,i/32],[0,i/32]] for i in range(32)]
    action=CanvasAction(board(),strokes)
    assert len(created)>1 and all(len(batch)<=32 for batch in created)
    progress=[]
    result=action.run(None,on_stage=progress.append)
    assert result['motion_completed'] and len(result['stages'])==len(created)
    assert [p['completed_parts'] for p in progress]==sorted(p['completed_parts'] for p in progress)
    assert progress[-1]['batch']==len(created)
    with pytest.raises(RuntimeError):action.run(None,cancelled=lambda:True)
    assert action.stages==[]
    with pytest.raises(ValueError):CanvasAction(board(),[[[0,0],[2,2]]])


def test_failed_batch_retains_evidence_without_advancing(monkeypatch):
    import tictactoe_gui.canvas_action as module
    class Batch:
        def __init__(self,*args,**kwargs):self.results=[]
        def run(self,*args,**kwargs):
            self.results=[{'stage':'1_lower','result':{'passed':True}}]
            raise RuntimeError('feedback stale')
    monkeypatch.setattr(module,'CanvasDrawing',Batch)
    action=CanvasAction(board(),[[[.5,.5],[.6,.5]]])
    with pytest.raises(RuntimeError,match='feedback stale'):action.run(None)
    assert action.stages[0]['stage']=='1_lower'


@pytest.mark.parametrize('gateway', [False,True])
def test_shared_canvas_http_large_payload_and_auth(tmp_path,gateway):
    session=WorkbenchSession(tmp_path,'real')
    session.update(state='ready',canvas=dict(width_mm=138.,height_mm=177.))
    backend=ThreadingHTTPServer(('127.0.0.1',0),make_handler(session))
    servers=[backend]
    origin='https://test.robotigniteacademy.com'
    if gateway:servers.append(ThreadingHTTPServer(('127.0.0.1',0),make_gateway(origin+'/slot/webpage/',backend.server_port)))
    threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
    for t in threads:t.start()
    base=f'http://127.0.0.1:{servers[-1].server_port}'
    def post(path,data,token=True):
        headers={'Content-Type':'application/json','Origin':origin if gateway else base}
        if token:headers['X-Workbench-Token']=session.token
        return urlopen(Request(base+path,data=json.dumps(data).encode(),headers=headers))
    try:
        for path in ('/canvas','/canvas.js','/canvas.css','/api/canvas/asset/chair'):
            with urlopen(base+path) as r: assert r.status==200
        with urlopen(base+'/api/config') as r:assert json.load(r)['canvas']['width_mm']==138.
        with pytest.raises(HTTPError) as e:urlopen(base+'/api/canvas/asset/unknown')
        assert e.value.code==404
        data=dict(strokes=[[[i/999,.5] for i in range(1000)]],speed=.1,kind='reset')
        assert len(json.dumps(data))>4096
        with pytest.raises(HTTPError) as e:post('/api/canvas',data,False)
        assert e.value.code==403 and session.jobs.empty()
        with pytest.raises(HTTPError) as e:post('/api/command',data)
        assert e.value.code==400 and session.jobs.empty()
        with post('/api/canvas',data) as r:assert r.status==202
        command=session.jobs.get_nowait()
        assert command['kind']=='canvas' and command['strokes']==data['strokes']
        with pytest.raises(HTTPError) as e:post('/api/canvas',data)
        assert e.value.code==409
        with post('/api/stop',{}) as r:assert r.status==202
        assert session.stop.is_set()
    finally:
        for s in reversed(servers):s.shutdown();s.server_close()
        for t in threads:t.join()


@pytest.mark.parametrize('data', [dict(strokes=[]),dict(strokes=[[[0,0],[True,1]]]),dict(strokes=[[[0,0],[1,1]]],speed=1.01)])
def test_canvas_rejects_invalid_input(data):
    with pytest.raises(ValueError):validate_command(dict(data,kind='canvas'),'real')


def test_real_canvas_can_select_direct_approach_per_command():
    draw = dict(kind='canvas', strokes=[[[0, 0], [1, 1]]])
    assert 'direct_from_zero' not in validate_command(draw, 'real')
    assert validate_command(dict(draw, direct_from_zero=True), 'real')['direct_from_zero'] is True
    with pytest.raises(ValueError, match='must be a boolean'):
        validate_command(dict(draw, direct_from_zero='true'), 'real')

@pytest.mark.parametrize('length,candidate', [(.085, True), (.120, True), (.130, True)])
def test_long_straight_source_preserves_segmented_fallback(length, candidate):
    canvas = board()
    half = length/(2*(canvas.x1-canvas.x0-.002))
    action = CanvasAction(canvas, [[[.5-half,.5],[.5+half,.5]]])
    assert bool(action.drawings[0].fallback) is candidate
    if candidate:
        assert len(action.prepared) == 1
        assert len(action.drawings[0].fallback[1]) > 1
    else:
        assert len(action.prepared) > 1


def test_plan_rejection_retries_before_any_ink_and_execution_error_stops():
    from geometry_msgs.msg import Pose
    from tictactoe_motion.actions.stroke_drawing import StrokeDrawing

    class Driver:
        def __init__(self, fail=False):
            self.pose = Pose()
            self.draws = []
            self.fail = fail

        def current_pose(self):
            return self.pose

        def linear(self, point):
            self.pose.position = point
            return {'passed': True}

        def path(self, poses, allow_plan_retry=False):
            if allow_plan_retry:
                if self.fail:
                    raise RuntimeError('execution failed')
                return None
            self.draws.append(poses)
            self.pose.position = poses[-1].position
            return {'passed': True}

    a, b, c = (Pose() for _ in range(3))
    b.position.x, c.position.x = .04, .08
    upper = Pose()
    upper.position.z = .01
    drawing = StrokeDrawing('cross')
    driver = Driver()
    stages = drawing.run_strokes(driver, [[a,b,c]], upper, lambda: False, lambda _: None,
                                 {1:[[a,b],[b,c]]})
    assert len(driver.draws) == 2
    assert [stage['stage'] for stage in stages] == [
        '1_lower', '1_draw', '1_fallback_1_draw', '1_fallback_1_lift',
        '1_fallback_2_lower', '1_fallback_2_draw', '1_fallback_2_lift']
    failing_driver = Driver(fail=True)
    with pytest.raises(RuntimeError, match='execution failed'):
        drawing.run_strokes(failing_driver, [[a,b,c]], upper, lambda: False, lambda _: None,
                            {1:[[a,b],[b,c]]})
    assert not failing_driver.draws


def test_real_canvas_approach_splits_only_rejected_plan():
    from geometry_msgs.msg import Point
    from tictactoe_motion.canvas.canvas_drawing import CanvasDrawing

    class Driver:
        def __init__(self, reject):
            self.reject = reject
            self.calls = []

        def linear(self, point, *, allow_excursion_retry=False):
            self.calls.append((point, allow_excursion_retry))
            return None if allow_excursion_retry and self.reject else {'passed': True}

    start = Point(x=0.12, y=-0.1, z=.216)
    end = Point(x=0.12, y=.03, z=.216)
    direct = Driver(False)
    assert CanvasDrawing.real_approach(direct, start, end, lambda: False)['passed']
    assert len(direct.calls) == 1
    split = Driver(True)
    result = CanvasDrawing.real_approach(split, start, end, lambda: False)
    assert result['approach_segments'] == 3
    assert [point.y for point, _ in split.calls[1:]] == pytest.approx([-.1+.13/3, -.1+.26/3, .03])
    assert all(point.z == .216 and not retry for point, retry in split.calls[1:])
    with pytest.raises(RuntimeError, match='cancelled'):
        CanvasDrawing.real_approach(split, start, end, lambda: True)


def test_small_closed_circle_preserves_one_stroke_with_preflight_fallback():
    import math
    from tictactoe_gui.canvas_action import continuous_closed_curve
    canvas = board()
    radius = .011
    raw = [[[.5+radius*math.cos(t*2*math.pi/128)/.136,
              .5+radius*math.sin(t*2*math.pi/128)/.175] for t in range(129)]]
    action = CanvasAction(canvas, raw)
    assert len(action.prepared) == 1
    assert len(action.drawings[0].fallback[1]) == 2
    path = action.prepared[0]['points']
    assert path[0] == pytest.approx(path[-1])
    assert len(path) >= 129
    assert continuous_closed_curve([[[0,0],[.1,0]],[[.1,0],[.1,.1],[0,0]]],1,1) is None


def test_long_or_open_curves_keep_lifted_segments():
    import math
    from tictactoe_gui.canvas_action import continuous_closed_curve
    circle = [[.5+.09*math.cos(t*2*math.pi/128),
               .5+.09*math.sin(t*2*math.pi/128)] for t in range(129)]
    assert continuous_closed_curve([circle[:65],circle[64:]],1,1) is None
    circle = [[.5+.011*math.cos(t*2*math.pi/128),
               .5+.011*math.sin(t*2*math.pi/128)] for t in range(120)]
    assert continuous_closed_curve([circle[:65],circle[64:]],1,1) is None

def test_drawing_and_transfer_speeds_are_separate_and_restore_on_failure(monkeypatch):
    from types import SimpleNamespace as S
    from tictactoe_motion.canvas.canvas_drawing import CanvasDrawing
    c=board()
    d=CanvasDrawing(c,[[[.5,.5],[.6,.5]]],upper_z=.211,depth=.005,transfer_z=.216)
    calls=[]
    node=S(cartesian_planner=S(canvas_native_timing=False),
           get_parameter=lambda key:S(value=.4 if key=='velocity_scaling' else .3))
    driver=S(node=node,recording=S(environment='real'),parameters=lambda **kw:calls.append(kw))
    def fail(driver, cancelled, progress):
        for name in ('raise_before_transfer','approach_hover','1_lower','1_draw','1_lift','exit_lift'):
            progress(name)
            assert driver.node.cartesian_planner.canvas_native_timing
        raise RuntimeError('feedback stale')
    monkeypatch.setattr(d,'_run',fail)
    with pytest.raises(RuntimeError,match='feedback stale'):d.run(driver)
    fast=dict(velocity_scaling=1.,acceleration_scaling=1.)
    requested=dict(velocity_scaling=.4,acceleration_scaling=.3)
    assert calls == [fast, fast, fast, requested, fast, fast, requested]
    assert not driver.node.cartesian_planner.canvas_native_timing

@pytest.mark.parametrize('axis,length', [('x',.134),('y',.173)])
def test_full_board_line_is_one_candidate_with_segmented_backup(axis,length):
    c=board(); usable=(c.x1-c.x0-.002) if axis=='x' else (c.y1-c.y0-.002)
    half=length/(2*usable)
    pts=[[[.5-half,.5],[.5+half,.5]]] if axis=='x' else [[[.5,.5-half],[.5,.5+half]]]
    a=CanvasAction(c,pts)
    assert len(a.prepared)==1
    assert len(a.drawings[0].fallback[1])>=3


def test_120mm_circle_remains_closed_and_has_segmented_backup():
    import math
    c=board();rx=.06/(c.x1-c.x0-.002);ry=.06/(c.y1-c.y0-.002)
    pts=[[[.5+rx*math.cos(t*2*math.pi/256),.5+ry*math.sin(t*2*math.pi/256)] for t in range(257)]]
    a=CanvasAction(c,pts)
    assert len(a.prepared)==1
    assert len(a.drawings[0].fallback[1])>=6
    assert a.prepared[0]['points'][0]==pytest.approx(a.prepared[0]['points'][-1])

def test_continuous_candidate_uses_bounded_excursion_only_before_fallback():
    from geometry_msgs.msg import Pose
    from tictactoe_motion.actions.stroke_drawing import StrokeDrawing
    class Driver:
        def __init__(self):self.pose=Pose();self.calls=[]
        def current_pose(self):return self.pose
        def linear(self, point):self.pose.position=point;return {'passed':True}
        def path(self, poses, **options):
            self.calls.append(options)
            if options.get('allow_plan_retry'):return None
            self.pose=poses[-1];return {'passed':True}
    p=[Pose(),Pose(),Pose()];p[1].position.x=.04;p[2].position.x=.08
    upper=Pose();upper.position.z=.01;d=Driver()
    StrokeDrawing('cross').run_strokes(d,[p],upper,lambda:False,lambda _:None,
        {1:[p[:2],p[1:]]},candidate_excursion_limit=1.)
    assert d.calls==[{'allow_plan_retry':True,'excursion_limit':1.},{},{}]

@pytest.mark.parametrize('kind,extra', [
    ('canvas', {'strokes': [[[.4,.4],[.6,.6]]]}),
    ('draw', {'shape':'x', 'size':.012})])
def test_real_drawing_defaults_to_45_percent(kind, extra):
    assert validate_command(dict(kind=kind, **extra), 'real')['speed'] == .45
