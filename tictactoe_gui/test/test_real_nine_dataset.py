"""Dataset safeguards and equivalence to the live four-zone camera preprocessing."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import cv2
import numpy as np
import pytest
import torch
from tictactoe_gui.perception_preview import PerceptionPreview
source=Path(__file__).resolve().parents[2]/'tools/prepare_real_nine_dataset.py'
spec=importlib.util.spec_from_file_location('nine_data',source)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_training_crops_match_live_preprocessing():
    raw=np.random.default_rng(3).integers(0,255,(240,424,3),dtype=np.uint8)
    h=cv2.getPerspectiveTransform(np.float32([[212.5,65.5],[256,65.5],[260.3,110],[209.4,110]]),np.float32([[140,189],[280,189],[280,378],[140,378]]))
    captured=[]
    class Model:
        def predict(self,images,**kwargs):
            captured.extend(images)
            return [SimpleNamespace(boxes=SimpleNamespace(data=torch.empty((0,6))),names={0:'X',1:'O'}) for _ in images]
    p=PerceptionPreview();p.model=Model();assert p._detect(raw,h,9)=={}
    regions=module.crop_regions(raw.shape,h)
    assert len(captured)==len(regions)==4
    for image,(left,top,right,bottom) in zip(captured,regions):
        assert np.array_equal(image,raw[top:bottom,left:right])


def test_padding_neighbors_are_labeled_and_partial_neighbors_exclude_crop():
    result=module.crop_labels([(0,np.array([20.,20.,30.,30.])),(1,np.array([70.,70.,80.,80.]))],(0,0,100,100))
    assert len(result)==2
    assert module.crop_labels([(0,np.array([95.,20.,105.,30.]))],(0,0,100,100)) is None


def test_review_must_match_actual_image_bytes(tmp_path):
    p=tmp_path/'frame.jpg';p.write_bytes(b'original')
    with pytest.raises(ValueError):module.check_review(p,{})
    entry={p.name:dict(approved=True,sha256=module.digest(p))}
    module.check_review(p,entry)
    p.write_bytes(b'changed')
    with pytest.raises(ValueError):module.check_review(p,entry)


def test_incomplete_groups_cannot_be_exported_as_frozen_test_set(tmp_path):
    (tmp_path/'manifest.json').write_text('[]')
    with pytest.raises(ValueError,match='twelve'):
        module.prepare(tmp_path,tmp_path/'missing',tmp_path/'out',None,None,None)

def test_edge_split_requires_all_eight_groups_and_keeps_a_real_test_set(tmp_path):
    (tmp_path/'manifest.json').write_text('[]')
    with pytest.raises(ValueError,match='all 8 complete'):
        module.prepare(tmp_path,tmp_path/'missing',tmp_path/'out',None,None,None,expected_counts=(4,2,2))
    with pytest.raises(ValueError,match='positive train'):
        module.prepare(tmp_path,tmp_path/'missing',tmp_path/'out',None,None,None,expected_counts=(8,0,0))

def test_unreadable_crop_is_never_exported_as_background():
    box=(0,np.array([70.,20.,80.,30.]))
    assert module.crop_labels([box],(0,0,50,50)) == []
    assert module.crop_labels([box],(50,0,100,50)) != []
    assert module.crop_labels([box],(0,0,75,50)) is None


def test_cell_evaluation_reports_but_does_not_score_unreadable_cells():
    path=source.with_name('evaluate_real_nine.py')
    spec=importlib.util.spec_from_file_location('nine_eval',path)
    evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
    result=evaluation.compare_cells([dict(row=0,col=8,mark='X'),dict(row=8,col=0,mark='O')],
                                    {(0,8):{'O'},(8,0):{'O'}},[(0,8)])
    assert result['tp']==1 and result['fn']==[] and result['fp']==[] and result['exact']
    assert result['ignored_cells']==[(0,8)]