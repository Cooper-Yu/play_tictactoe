"""Freehand requests never supply a committed row or column."""
import pytest
from tictactoe_gui.server import CanvasSession
from tictactoe_gui.geometry import prepare_game_strokes, verify_handwriting_cell
from tictactoe_perception.stable_player_move import StablePlayerMove

X = [[[.10,.10],[.23,.23]], [[.23,.10],[.10,.23]]]

def ready(tmp_path, **changes):
    s=CanvasSession(tmp_path, None, vision_available=True)
    s.update(state='ready', game=dict(size=3, revision=4, phase='player',
             input_source='handwriting', board=[['']*3 for _ in range(3)]))
    s.update(**changes)
    return s

def test_freehand_queue_preserves_order_without_a_cell(tmp_path):
    s=ready(tmp_path)
    s.submit('game_handwriting', X, {'revision':4})
    job=s.jobs.get_nowait()
    assert job['strokes']==X
    assert 'row' not in job['game_request'] and 'col' not in job['game_request']
    assert [p['stroke'] for p in job['prepared']]==[1,2]
    assert not any(any(row) for row in s.status()['game']['board'])

@pytest.mark.parametrize('revision', [3,5])
def test_stale_draft_rejected(tmp_path, revision):
    s=ready(tmp_path)
    with pytest.raises(RuntimeError):
        s.submit('game_handwriting', X, {'revision':revision})
    assert s.jobs.empty()

@pytest.mark.parametrize('strokes', [[], [[[.5,.5]]], [[[.2,.2],[2,.3]]]])
def test_invalid_strokes_rejected_before_motion(tmp_path, strokes):
    s=ready(tmp_path)
    with pytest.raises(ValueError):
        s.submit('game_handwriting', strokes, {'revision':4})
    assert s.jobs.empty()

def test_real_handwriting_requires_a_current_camera_turn(tmp_path):
    s=CanvasSession(tmp_path,None,vision_available=True,environment='real')
    s.update(state='ready')
    with pytest.raises(RuntimeError):s.submit('game_handwriting',X,{'revision':1})
    s.update(game=dict(size=3,revision=4,phase='player',input_source='handwriting',
                       board=[['']*3 for _ in range(3)]))
    s.submit('game_handwriting',X,{'revision':4})
    job=s.jobs.get_nowait()
    assert job['strokes']==X and 'row' not in job['game_request']

@pytest.mark.parametrize('cells', [{(0,0):{'O'}}, {}, {(0,0):{'X'},(0,1):{'X'}}])
def test_wrong_missing_or_multiple_marks_cannot_change_turn(cells):
    gate=StablePlayerMove([['']*3 for _ in range(3)],'X')
    assert all(gate.observe(i,cells) is None for i in range(1,7))

def test_cross_cell_not_accepted_even_with_one_detection():
    with pytest.raises(RuntimeError):verify_handwriting_cell([[[.1,.1],[.6,.1]]],(0,0,'X'),3)
    verify_handwriting_cell(X,(0,0,'X'),3)

def test_duplicate_occupied_cell_does_not_advance():
    gate=StablePlayerMove([['X','',''],['','',''],['','','']],'O')
    assert all(gate.observe(i,{(0,0):{'X','O'}}) is None for i in range(1,6))

def test_grid_mapping_keeps_top_left_in_top_left():
    parts=prepare_game_strokes(X)
    assert parts[0]['points'][0][0] > .5
    assert parts[0]['points'][0][1] > .5


@pytest.mark.parametrize('points', [
    [[.43,.10],[.57,.23],[.43,.23],[.43,.10]],
    [[.1,.1],[.2,.1],[.2,.2],[.1,.2],[.1,.1]],
])
def test_polygon_veto_even_if_yolo_calls_it_x_or_o(points):
    from tictactoe_gui.geometry import verify_handwriting_shape
    with pytest.raises(RuntimeError, match='closed polygon'):
        verify_handwriting_shape([points])


def test_polygon_veto_preserves_ellipses_and_x():
    import math
    from tictactoe_gui.geometry import verify_handwriting_shape
    circle=[[.5+.09*math.cos(i/56*2*math.pi),.5+.067*math.sin(i/56*2*math.pi)]
            for i in range(57)]
    verify_handwriting_shape([circle])
    verify_handwriting_shape(X)
    verify_handwriting_shape([circle[:48]])
