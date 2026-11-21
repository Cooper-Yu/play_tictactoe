"""Check the offline comparison's accounting before interpreting model scores."""
from compare_real_models import match_boxes, compare_cells


def box(mark='X', coords=(0,0,10,10)):
    return dict(mark=mark,xyxy=coords)


def test_duplicate_cannot_count_as_two_true_positives():
    result=match_boxes([box()],[box(),box()])
    assert (result['tp'],result['fn'],result['fp'],result['duplicate_fp'])==(1,0,1,1)
    assert not result['exact']


def test_wrong_class_is_a_miss_and_false_positive():
    result=match_boxes([box()],[box('O')])
    assert (result['tp'],result['fn'],result['fp'])==(0,1,1)


def test_bad_box_location_cannot_pass_iou_matching():
    result=match_boxes([box()],[box(coords=(20,20,30,30))])
    assert (result['tp'],result['fn'],result['fp'])==(0,1,1)


def test_ignored_unreadable_cells_do_not_count_as_correct_or_wrong():
    result=compare_cells({(0,0):{'X'},(0,1):{'O'}},{(0,0):{'X'},(0,1):{'X'}},[(0,1)])
    assert (result['tp'],result['fn'],result['fp'])==(1,0,0)
    assert result['exact']


def test_same_cell_conflict_cannot_be_silently_deduplicated():
    result=compare_cells({(0,0):{'X'}},{(0,0):{'X','O'}},[])
    assert (result['tp'],result['fn'],result['fp'],result['conflicts'])==(1,0,1,1)
    assert not result['exact']
