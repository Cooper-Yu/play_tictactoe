"""Verify real GUI vision turns without sending robot commands."""
import threading
import time
from types import SimpleNamespace

import pytest
from tictactoe_gui.server import CanvasSession
from tictactoe_gui import real_game


def test_real_session_rejects_direct_state_move(tmp_path):
    s = CanvasSession(tmp_path, None, vision_available=True, environment='real')
    s.update(state='ready')
    with pytest.raises(ValueError):
        s.submit('game_move', game_request={'row':0, 'col':0, 'revision':1})
    with pytest.raises(ValueError):
        s.submit('game_start', game_request={'size':3, 'input_source':'click'})


@pytest.mark.parametrize("source", ["vision", "handwriting"])
@pytest.mark.parametrize("size,mode,cell", [(3,"classic",0), (9,"four",8)])
def test_proxy_turn_is_committed_only_after_three_camera_frames(monkeypatch, tmp_path, size, mode, cell, source):
    world = SimpleNamespace(cells={}, sequence=0, moves=[], detection_sequences=[])
    class Response:
        content = b'camera'
        def raise_for_status(self):
            pass
        def json(self):
            world.sequence += 1
            return {'camera': {'sequence':world.sequence, 'fresh':True, 'age_s':0}, 'fresh':True}
    class HTTP:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, *args, **kwargs):
            return Response()
    class Client:
        def __init__(self, url, output, **kwargs):
            self.url = url
        def command(self, **kwargs):
            world.moves.append(kwargs['kind'])
            if kwargs['kind']=='canvas':world.cells[(cell,cell)]=frozenset(('X',))
        def park(self, *args):
            pass
    class Actions:
        width, height = .144, .193
        def __init__(self, client):
            pass
        def grid_strokes(self, *args):
            pass
        x_strokes = o_strokes = grid_strokes
        def draw_grid(self, *args, **kwargs):
            return {'passed':True}
        def draw_x(self, *args, **kwargs):
            world.cells[(cell,cell)] = frozenset(('X',))
            return {'passed':True}
        def draw_o(self, *args, **kwargs):
            assert len(set(world.detection_sequences)) >= 3
            world.moves.append('O')
            return {'passed':True}
    class Perception:
        def detect_cells(self, image, size=3):
            if world.cells:
                world.detection_sequences.append(world.sequence)
            return dict(world.cells)
    monkeypatch.setattr(real_game.requests, 'Session', HTTP)
    monkeypatch.setattr(real_game, 'Workstation', Client)
    monkeypatch.setattr(real_game, 'RemoteDrawing', Actions)
    s = CanvasSession(tmp_path, None, vision_available=True, environment='real')
    thread = threading.Thread(target=real_game.real_game_worker,
        args=(s,), kwargs={'url':'http://test/', 'perception':Perception()}, daemon=True)
    thread.start()
    def wait(predicate):
        deadline=time.monotonic()+5
        while not predicate():
            assert time.monotonic()<deadline
            time.sleep(.02)
    try:
        wait(lambda:s.status()['state']=='ready')
        s.submit('game_start', game_request={'size':size,'mode':mode,'input_source':source})
        wait(lambda:not s.status()['busy'])
        revision=s.status()['game']['revision']
        if source == 'handwriting':
            center=(cell+.5)/size;d=.15/size
            strokes=[[[center-d,center-d],[center+d,center+d]],
                     [[center+d,center-d],[center-d,center+d]]]
            s.submit('game_handwriting',strokes,{'revision':revision})
        else:
            s.submit('game_vision_move', game_request={'row':cell,'col':cell,'revision':revision})
        wait(lambda:not s.status()['busy'])
        assert s.status()['state']=='ready', s.status()
        assert s.status()['game']['board'][cell][cell]=='X'
        assert sum(mark=='O' for row in s.status()['game']['board'] for mark in row)==1
        assert world.moves==(['reset','canvas','O'] if source=='handwriting' else ['reset','O'])
        assert s.status()['vision']['consecutive']==3
    finally:
        s.shutdown.set()
        thread.join(timeout=3)


def test_offline_startup_retains_finished_board_without_motion(monkeypatch, tmp_path):
    import json
    saved = tmp_path/'game.json'
    board = [['X','O','X'],['','O',''],['','O','X']]
    saved.write_text(json.dumps({'game':{'phase':'finished','input_source':'vision','board':board,'size':3}}))
    (tmp_path/'finished.jpg').write_bytes(b'saved-camera')
    s = CanvasSession(tmp_path/'output', None, vision_available=True, environment='real')
    def unavailable(*args, **kwargs):
        s.shutdown.set()
        raise real_game.requests.ConnectionError('offline')
    monkeypatch.setattr(real_game, 'Workstation', unavailable)
    real_game.real_game_worker(s, url='http://test/', perception=None, restore=saved)
    assert s.status()['frame_source']=='saved'
    assert s.status()['game']['board']==board
    assert s.camera_image()==b'saved-camera'
    assert s.status()['state']=='offline'


def test_blocked_session_can_explicitly_clear_but_not_resume(tmp_path):
    session = CanvasSession(tmp_path, None, environment='real', vision_available=True)
    session.update(state='blocked', busy=False)
    with pytest.raises(RuntimeError):
        session.submit('game_start', game_request={'size':3,'input_source':'vision'})
    assert session.submit('reset') == 1
    with pytest.raises(RuntimeError):
        session.submit('reset')


@pytest.mark.parametrize("size,mode", [(3,"classic"), (9,"four")])
@pytest.mark.parametrize("first_symbol", ["X","O"])
def test_two_players_real_worker_confirms_each_turn_without_ai(monkeypatch, tmp_path, size, mode, first_symbol):
    world = SimpleNamespace(cells={}, sequence=0, drawn=[], parks=[], target=(0,size-1))
    class Response:
        content = b"camera"
        def raise_for_status(self): pass
        def json(self):
            world.sequence += 1
            return {"camera":{"sequence":world.sequence,"fresh":True,"age_s":0},"fresh":True}
    class HTTP:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,*args,**kwargs): return Response()
    class Client:
        def __init__(self,*args,**kwargs): self.url="http://test/"
        def command(self,**kwargs): assert kwargs["kind"]=="reset"
        def park(self,name): world.parks.append(name)
    class Actions:
        width,height=.144,.193
        def __init__(self,client): pass
        def grid_strokes(self,*args): pass
        x_strokes=o_strokes=grid_strokes
        def draw_grid(self,*args,**kwargs): return {"passed":True}
        def draw_x(self,*args,**kwargs): return self.draw("X")
        def draw_o(self,*args,**kwargs): return self.draw("O")
        def draw(self,mark):
            # The state must still be empty while the actual stroke is drawn.
            assert session.status()["game"]["board"][world.target[0]][world.target[1]]==""
            world.drawn.append(mark);world.cells[world.target]=frozenset((mark,))
            return {"passed":True}
    class Perception:
        def detect_cells(self,image,size=3): return dict(world.cells)
    monkeypatch.setattr(real_game.requests,"Session",HTTP)
    monkeypatch.setattr(real_game,"Workstation",Client)
    monkeypatch.setattr(real_game,"RemoteDrawing",Actions)
    monkeypatch.setattr("tictactoe_game.grid_game.GridGame.suggest_move",
                        lambda *a,**k:pytest.fail("Two-player game called AI"))
    session=CanvasSession(tmp_path,None,environment="real",vision_available=True)
    thread=threading.Thread(target=real_game.real_game_worker,args=(session,),
                            kwargs={"url":"http://test/","perception":Perception()},daemon=True)
    def wait(predicate):
        deadline=time.monotonic()+5
        while not predicate():
            assert time.monotonic()<deadline,session.status()
            time.sleep(.01)
    thread.start()
    try:
        wait(lambda:session.status()["state"]=="ready")
        session.submit("game_start",game_request={"size":size,"mode":mode,"input_source":"vision",
                                                 "opponent":"human","mark":first_symbol})
        wait(lambda:not session.status()["busy"])
        for row,mark in ((0,first_symbol),(1,"O" if first_symbol=="X" else "X")):
            world.target=(row,size-1)
            before=len(world.drawn)
            session.submit("game_vision_move",game_request={"row":row,"col":size-1,
                            "revision":session.status()["game"]["revision"]})
            wait(lambda:not session.status()["busy"])
            s=session.status()
            assert s["state"]=="ready",s
            assert s["game"]["board"][row][size-1]==mark
            assert s["vision"]["consecutive"]==3
            assert len(world.drawn)==before+1
            assert world.parks[-1]=="zero"
        assert session.status()["game"]["turn"]==first_symbol
        assert session.status()["game"]["phase"]=="player"
    finally:
        session.shutdown.set();thread.join(timeout=3)


@pytest.mark.parametrize("options", [{"opponent":"unknown"}, {"opponent":"human","mode":"score"},
                                    {"opponent":"human","first":"ai"}])
def test_two_player_bad_setup_cannot_queue_reset(tmp_path, options):
    session=CanvasSession(tmp_path,None,vision_available=True,environment="real")
    session.update(state="ready")
    with pytest.raises(ValueError):
        session.submit("game_start",game_request={"size":3,"input_source":"vision",**options})
    assert session.jobs.empty() and session.status()["job"]==0


@pytest.mark.parametrize('width,height',[(.138,.177),(.144,.193)])
def test_real_handwriting_insets_match_physical_grid(width,height):
    strokes=[[[0.,0.],[.5,.5],[1.,1.]]]
    mapped=real_game.real_handwriting_strokes(strokes,width,height)
    for (u,v),(x,y) in zip(strokes[0],mapped[0]):
        assert .001+x*(width-.002)==pytest.approx(.002+u*(width-.004))
        assert .001+y*(height-.002)==pytest.approx(.002+v*(height-.004))
