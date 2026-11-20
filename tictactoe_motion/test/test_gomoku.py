"""Configurable-grid geometry and freestyle five-in-a-row failure boundaries."""
import math
from unittest.mock import Mock
import pytest
from test_drawing_actions import actions
from tictactoe_game.gomoku import Gomoku


def game(size=9):
    a=actions()
    for name in ('draw_grid','draw_x','draw_o'):setattr(a,name,Mock(return_value={'passed':True}))
    return Gomoku(a,size=size)


@pytest.mark.parametrize('rows,cols',[(3,3),(5,7),(9,9),(15,15)])
def test_internal_lines_count_and_spacing(rows,cols):
    a=actions();paths=a._prepare(a.grid_strokes(width=.09,height=.09,rows=rows,columns=cols)).paths
    assert len(paths)==rows+cols-2
    vertical=[p for p in paths if math.isclose(p[0][0],p[-1][0])]
    horizontal=[p for p in paths if math.isclose(p[0][1],p[-1][1])]
    assert len(vertical)==cols-1 and len(horizontal)==rows-1
    assert all(math.isclose(b[0][0]-a[0][0],.09/cols) for a,b in zip(vertical,vertical[1:]))
    assert all(math.isclose(abs(b[0][1]-a[0][1]),.09/rows) for a,b in zip(horizontal,horizontal[1:]))


@pytest.mark.parametrize('size',[5,9,15])
def test_cell_centers_and_symbol_scaling(size):
    g=game(size);g.start();g.play('X',0,0);g.play('O',size-1,size-1)
    args=g.actions.draw_x.call_args.args
    assert math.isclose(args[1],.09/size*.55)
    args=g.actions.draw_o.call_args.args
    assert math.isclose(args[1],.09/size*.25)
    assert len(g.board)==size*size


@pytest.mark.parametrize('dr,dc',[(0,1),(1,0),(1,1),(1,-1)])
def test_five_in_all_axes_and_both_directions(dr,dc):
    g=game()
    for offset in range(-2,3):g.board[(4+dr*offset)*9+4+dc*offset]='X'
    assert g.has_line('X',4,4)
    g.board[(4+dr*2)*9+4+dc*2]=''
    assert not g.has_line('X',4,4)


def test_gaps_edges_and_overline():
    g=game()
    for col in (0,1,2,4,5,6):g.board[col]='X'
    assert not g.has_line('X',0,2)
    g.board[3]='X';assert g.has_line('X',0,3)
    g=game()
    for index in (7,8,9,10,11):g.board[index]='X'
    assert not g.has_line('X',0,8)  # A flattened-array row boundary is not a line.


def test_complete_game_only_commits_successful_legal_turns():
    g=game();g.start()
    for col in range(4):g.play('X',4,col);g.play('O',5,col)
    assert g.phase=='playing';g.play('X',4,4)
    assert g.outcome=='X' and g.phase=='finished'
    with pytest.raises(ValueError):g.play('O',5,4)
    g=game();g.start();g.actions.draw_x.return_value={'passed':False}
    with pytest.raises(RuntimeError):g.play('X',4,4)
    assert not any(g.board) and g.phase=='blocked'


@pytest.mark.parametrize('size',[4,16,True,9.5])
def test_invalid_board_size_never_requests_drawing(size):
    with pytest.raises(ValueError):game(size)
