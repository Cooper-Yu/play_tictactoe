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
from tictactoe_motion.board_canvas import BoardCanvas


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
    strokes=[[[0,i/32],[1,i/32]] for i in range(32)]
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


@pytest.mark.parametrize('data', [dict(strokes=[]),dict(strokes=[[[0,0],[True,1]]]),dict(strokes=[[[0,0],[1,1]]],speed=.2)])
def test_canvas_rejects_invalid_input(data):
    with pytest.raises(ValueError):validate_command(dict(data,kind='canvas'),'real')