import importlib.util,json
from pathlib import Path
import pytest

source=Path(__file__).resolve().parents[2]/'tools/collect_xo_real_nine.py'
spec=importlib.util.spec_from_file_location('collector',source)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class FakeClient:
    calls=[]
    fail_at=None
    def __init__(self,*args,**kwargs):
        self.sequence=0;self.http=self;self.url='http://test/'
    def command(self,**command):
        self.calls.append(command)
        if len(self.calls)==self.fail_at:raise RuntimeError('feedback interruption')
    def park(self,*args):pass
    def stop(self):raise AssertionError('Not executing in this fake')
    def get(self,route,**kwargs):
        if route.startswith('http'):return self
        self.sequence+=4
        return dict(camera=dict(sequence=self.sequence,fresh=True,age_s=0),busy=False,pose={})
    content=b'jpeg'
    def raise_for_status(self):pass

class Geometry:
    width=.138;height=.177
    def __init__(self,client):pass
    def grid_strokes(self,*args,**kwargs):return [[(.1,.1),(.9,.1)]]
    def x_strokes(self,c,s):return [[(c[0]-s/self.width/2,c[1]),(c[0]+s/self.width/2,c[1])]]
    def o_strokes(self,c,r):return [[(c[0]-r/self.width,c[1]),(c[0]+r/self.width,c[1])]]

@pytest.fixture(autouse=True)
def mocks(monkeypatch):
    FakeClient.calls=[];FakeClient.fail_at=None
    monkeypatch.setattr(module,'Workstation',FakeClient)
    monkeypatch.setattr(module,'RemoteDrawing',Geometry)
    monkeypatch.setattr(module.time,'time',lambda:1795238200.)

def test_twelve_independent_groups_and_incremental_layouts(tmp_path):
    module.collect(tmp_path,deadline_epoch=1795243979.)
    complete=list(tmp_path.glob('board-*/COMPLETE'));assert len(complete)==12
    metadata=[json.loads(p.read_text()) for p in tmp_path.glob('board-*/attempt-*/layout-*.json')]
    assert len(metadata)==60
    assert {s:len({d['group'] for d in metadata if d['split']==s}) for s in ('train','val','test')}=={'train':8,'val':2,'test':2}
    assert sorted(len(d['marks']) for d in metadata)==sorted([0,2,4,6,8]*12)
    for d in metadata:
        assert len({(m['row'],m['col']) for m in d['marks']})==len(d['marks'])
    previous=len(FakeClient.calls);module.collect(tmp_path,deadline_epoch=1795243979.);assert len(FakeClient.calls)==previous

def test_motion_failure_is_logged_without_automatic_replay(tmp_path):
    FakeClient.fail_at=2
    with pytest.raises(RuntimeError,match='feedback interruption'):module.collect(tmp_path,1,deadline_epoch=1795243979.)
    assert len(FakeClient.calls)==2
    assert len(list(tmp_path.glob('board-*/attempt-*/FAILED.json')))==1
    assert not list(tmp_path.glob('board-*/COMPLETE'))

def test_stop_file_prevents_motion(tmp_path):
    (tmp_path/'STOP').touch()
    with pytest.raises(RuntimeError,match='deadline/stop'):module.collect(tmp_path,1,deadline_epoch=1795243979.)
    assert not FakeClient.calls


def test_expired_or_nonfinite_deadline_prevents_motion(tmp_path):
    for deadline in (1795238199., float('nan'), float('inf')):
        with pytest.raises(ValueError, match='deadline'):
            module.collect(tmp_path, deadline_epoch=deadline)
    assert not FakeClient.calls


def test_current_booking_guard_prevents_motion(tmp_path):
    guard = tmp_path/'current-booking-stop'
    guard.touch()
    with pytest.raises(RuntimeError, match='deadline/stop'):
        module.collect(tmp_path, deadline_epoch=1795243979., guard_file=guard)
    assert not FakeClient.calls


def test_old_booking_guard_does_not_cancel_new_booking(tmp_path):
    old = tmp_path.parent/'robustness_20261121'/'closeout_requested'
    old.parent.mkdir(exist_ok=True)
    old.touch()
    module.collect(tmp_path, 1, deadline_epoch=1795243979.)
    assert len(list(tmp_path.glob('board-*/COMPLETE'))) == 1