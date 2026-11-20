"""Parameter geometry, rules and commit-after-success checks without hardware."""
import math
from pathlib import Path
from unittest.mock import Mock
import pytest
import yaml
from tictactoe_motion.board_canvas import BoardCanvas
from tictactoe_motion.drawing_actions import DrawingActions
from tictactoe_game.tic_tac_toe import TicTacToe


def actions():return DrawingActions(BoardCanvas(yaml.safe_load((Path(__file__).parents[1]/'config/board_sim.yaml').read_text())))


@pytest.mark.parametrize('center,width,height',[((.5,.5),.06,.06),((.55,.45),.04,.05),((.45,.6),.08,.07)])
def test_grid_metric_dimensions_and_four_separate_lines(center,width,height):
    a=actions();paths=a._prepare(a.grid_strokes(center,width,height)).paths
    assert len(paths)==4
    assert math.isclose(math.dist(paths[0][0],paths[0][-1]),height)
    assert math.isclose(math.dist(paths[1][0],paths[1][-1]),width)
    assert math.isclose(paths[2][0][0]-paths[0][0][0],width/3)


@pytest.mark.parametrize('radius',[.003,.005,.012])
def test_circle_radius_and_closed_path(radius):
    a=actions();path=a._prepare(a.o_strokes((.55,.55),radius)).paths[0]
    center=(a.canvas.x0+.55*a.width,a.canvas.y1-.55*a.height)
    assert path[0]==path[-1]
    assert all(math.isclose(math.dist(p[:2],center),radius,abs_tol=1e-12) for p in path)


@pytest.mark.parametrize('size',[.008,.012,.025])
def test_x_has_two_diagonals_of_requested_size(size):
    a=actions();paths=a._prepare(a.x_strokes((.5,.5),size)).paths
    assert len(paths)==2
    assert all(math.isclose(math.dist(path[0],path[-1]),math.sqrt(2)*size) for path in paths)


@pytest.mark.parametrize('call',[lambda a:a.grid_strokes((.01,.01)),lambda a:a.x_strokes(size=-.1),lambda a:a.o_strokes(radius=float('nan')),lambda a:a.o_strokes(samples=2)])
def test_invalid_parameters_rejected_before_driver(call):
    with pytest.raises(ValueError):call(actions())


def game():
    a=actions()
    for name in ('draw_grid','draw_x','draw_o'):setattr(a,name,Mock(return_value={'passed':True}))
    return TicTacToe(a)


def test_game_rejects_illegal_moves_and_detects_win():
    g=game();g.start();g.play('X',0,0)
    with pytest.raises(ValueError,match='occupied'):g.play('O',0,0)
    with pytest.raises(ValueError,match='turn'):g.play('X',1,1)
    g.play('O',1,0);g.play('X',0,1);g.play('O',1,1);g.play('X',0,2)
    assert g.outcome=='X' and g.phase=='finished'
    with pytest.raises(ValueError):g.play('O',2,0)
    assert g.actions.draw_x.call_count==3 and g.actions.draw_o.call_count==2


def test_game_failure_never_commits_a_phantom_mark():
    g=game();g.start();g.actions.draw_x.return_value={'passed':False}
    with pytest.raises(RuntimeError):g.play('X',0,0)
    assert g.board==['']*9 and g.phase=='blocked'
    with pytest.raises(ValueError):g.play('X',0,1)


def test_draw_and_cell_coordinate_validation():
    g=game();g.start()
    for symbol,row,col in [('X',0,0),('O',0,1),('X',0,2),('O',1,1),('X',1,0),('O',1,2),('X',2,1),('O',2,0),('X',2,2)]:g.play(symbol,row,col)
    assert g.outcome=='draw'
    with pytest.raises(ValueError):g.cell_center(True,0)
    with pytest.raises(ValueError):g.cell_center(3,0)


def test_preview_does_not_need_or_call_motion_driver():
    a=actions();a.grid_strokes();a.x_strokes();a.o_strokes()
    with pytest.raises(RuntimeError,match='explicit motion driver'):a.draw_x()
