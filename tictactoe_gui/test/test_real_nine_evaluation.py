"""Exercise whole-board exactness, class conflicts, and missing/extra detections."""
import importlib.util
from pathlib import Path

p=Path(__file__).resolve().parents[2]/'tools/evaluate_real_nine.py'
s=importlib.util.spec_from_file_location('evaluate_real_nine',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def test_cell_conflict_is_not_an_exact_board():
    result=m.compare_cells([dict(row=1,col=2,mark='X')],{(1,2):{'X','O'}})
    assert result['tp']==1 and result['conflicts']==1
    assert result['fp']==[(1,2,'O')] and not result['exact']


def test_wrong_cell_counts_as_both_missing_and_extra():
    result=m.compare_cells([dict(row=1,col=2,mark='X')],{(2,1):{'X'}})
    assert result['fn']==[(1,2,'X')] and result['fp']==[(2,1,'X')]


def test_empty_board_requires_no_predictions():
    assert m.compare_cells([], {})['exact']
    assert not m.compare_cells([], {(0,0):{'O'}})['exact']