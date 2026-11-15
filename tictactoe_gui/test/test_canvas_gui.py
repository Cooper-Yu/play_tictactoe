"""Geometry/HTTP acceptance checks that do not create ROS or issue motion."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
import pytest
from tictactoe_gui.geometry import prepare_strokes, metric_distance
from tictactoe_gui.server import CanvasSession, make_handler


@pytest.mark.parametrize('name',['chair','docker','smile'])
def test_bundled_preview_reproduces_existing_metric_source(name):
    from tictactoe_gui.geometry import load_illustration
    from importlib.resources import files
    asset=json.loads(files('tictactoe_motion').joinpath('illustrations',name+'.json').read_text())
    loaded=load_illustration(name)
    assert len(loaded['strokes'])==len(asset['strokes'])
    for source,preview in zip(asset['strokes'],loaded['strokes']):
        for (u,v),point in zip(source,preview):
            board_u=1-.001/.144-point[0]*(1-.002/.144)
            board_v=1-.001/.193-point[1]*(1-.002/.193)
            assert board_u==pytest.approx(.5-(u-.5)*.06/.144)
            assert board_v==pytest.approx(.5-(v-.5)*(.06/asset['aspect'])/.193)
    assert 1<=len(prepare_strokes(loaded['strokes']))<=256


def test_order_rotation_and_edge_footprint():
    parts = prepare_strokes([[[0,0],[.2,.1]], [[.5,.5],[.6,.5]]])
    assert [p['stroke'] for p in parts] == [1,2]
    assert parts[0]['points'][0] == pytest.approx([1-.001/.144,1-.001/.193])
    assert parts[1]['points'][0] == pytest.approx([.5,.5])


def test_long_path_split_preserves_order_and_geometry():
    parts = prepare_strokes([[[0,0],[1,1]]])
    assert len(parts)>1
    assert all(sum(metric_distance(a,b,.144,.193) for a,b in zip(p['points'],p['points'][1:]))<=.061 for p in parts)
    assert all(a['points'][-1]==b['points'][0] for a,b in zip(parts,parts[1:]))


@pytest.mark.parametrize('strokes',[[],None,[[[0,0]]],[[[float('nan'),0],[.2,.2]]],
    [[[0,0],[1.1,.5]]],[[[0,0],[True,.5]]],[[[.5,.5],[.5,.5]]],[[[0,0],[.1,.1]]]*33])
def test_invalid_input(strokes):
    with pytest.raises(ValueError):prepare_strokes(strokes)


def test_http_auth_busy_invalid_and_stop(tmp_path):
    session=CanvasSession(tmp_path,None);session.update(state='ready')
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(session))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def post(path,data,token=True,origin=None):
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
        headers={'Content-Type':'application/json'}
        if token:headers['X-Canvas-Token']=session.token
        if origin:headers['Origin']=origin
        connection.request('POST',path,json.dumps(data),headers)
        response=connection.getresponse();body=json.loads(response.read());connection.close()
        return response.status,body
    try:
        assert post('/api/draw',{'strokes':[[[.4,.4],[.5,.5]]]},False)[0]==403
        assert post('/api/draw',{},origin='http://external.invalid')[0]==403
        assert post('/api/draw',{'strokes':[[[0,0],[2,2]]]})[0]==400
        assert session.jobs.empty()
        assert post('/api/draw',{'strokes':[[[.4,.4],[.5,.5]]]})[0]==202
        assert post('/api/reset',{})[0]==409
        assert post('/api/stop',{})[0]==202 and session.stop.is_set()
        assert session.status()['state']=='stopping'
        assert post('/api/draw',[])[0]==400
    finally:
        server.shutdown();server.server_close();thread.join()


def test_tablet_reset_deletes_one_composite_not_each_stroke(tmp_path):
    from types import SimpleNamespace
    import xml.etree.ElementTree as ET
    import yaml
    from pathlib import Path
    from tictactoe_motion.simulated_board import SimulatedBoard
    profile=yaml.safe_load((Path(__file__).parents[2]/'tictactoe_motion/config/board_sim.yaml').read_text())
    models={};deletes=[];xml=[]
    class Service:
        def __init__(self,name):self.name=name
        def call_async(self,request):
            if self.name=='/spawn_entity':
                models[request.name]=request.xml;xml.append(request.xml)
            else:
                models.pop(request.name);deletes.append(request.name)
            return SimpleNamespace(success=True,status_message='ok')
    node=SimpleNamespace(create_client=lambda kind,name:Service(name))
    board=SimulatedBoard(node,profile,tmp_path,lambda value:value,grouped=True)
    samples=[{'xyz':[.19+i*.001,0,.21]} for i in range(6)]
    for _ in range(3):
        board.paint(samples)
        assert len(models)==len(board.models)==1
    assert len(ET.fromstring(xml[-1]).findall('.//visual'))==3
    before=len(deletes)
    board.clear()
    assert not models and len(deletes)-before==1
    board.paint(samples)
    assert len(ET.fromstring(xml[-1]).findall('.//visual'))==1
    board.close()


def test_only_known_readonly_gazebo_teardown_error_retries(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from tictactoe_motion.simulation_scene import model_pose
    error=SimpleNamespace(returncode=-6,stdout='',stderr='boost thread: trying joining itself: Resource deadlock avoided')
    good=SimpleNamespace(returncode=0,stdout='0 0 0 0 0 0',stderr='')
    run=Mock(side_effect=[error,good]);monkeypatch.setattr('tictactoe_motion.simulation_scene.subprocess.run',run)
    assert model_pose('/observed/gz','piper',{})==[0]*6 and run.call_count==2
    run.side_effect=[error,error]
    with pytest.raises(RuntimeError):model_pose('/observed/gz','piper',{})
    run.reset_mock();run.side_effect=[SimpleNamespace(returncode=1,stdout='',stderr='different error')]
    with pytest.raises(RuntimeError):model_pose('/observed/gz','piper',{})
    assert run.call_count==1
