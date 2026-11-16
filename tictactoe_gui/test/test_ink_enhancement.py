"""Verify selective ink enhancement without source mutation or frame inclusion."""
import cv2
import numpy as np
import pytest
from tictactoe_perception.image_enhancer import ImageEnhancer
from tictactoe_gui.workbench import enhance_frame


def scene():
    image=np.full((80,100,3),(30,20,10),np.uint8)
    image[:5]=(255,220,0)  # Blue/cyan frame excluded by the manual ROI.
    image[35:37,25:75]=(90,65,15)
    image[50:52,25:75]=(20,20,180)
    image[60:62,25:75]=(200,200,200)
    return image


def test_selective_existing_ink_and_manual_frame_exclusion():
    image=scene();original=image.copy();roi=(10,10,80,60)
    result=ImageEnhancer().enhance_ink(image,75,20,roi)
    cropped=original[10:70,10:90]
    assert result.shape==cropped.shape
    assert np.array_equal(image,original)
    assert result[25:27,15:65].mean()>cropped[25:27,15:65].mean()+20
    assert np.array_equal(result[40:42],cropped[40:42])  # Red stays red.
    assert np.array_equal(result[50:52],cropped[50:52])  # Neutral pixels unchanged.
    assert np.array_equal(result[0:5],cropped[0:5])  # Uniform blue board unchanged.
    assert np.array_equal(ImageEnhancer().enhance_ink(image,0,20,roi),cropped)


@pytest.mark.parametrize('query',[
    {'beta':['0'],'mode':['ink']},
    {'beta':['0'],'mode':['ink'],'roi':['.1,.1,.8,.8'],'strength':['nan']},
    {'beta':['0'],'mode':['ink'],'roi':['.1,.1,.8,.8'],'tolerance':['100']},
    {'beta':['0'],'mode':['unknown']}])
def test_http_image_parameters_reject_invalid_modes_or_regions(query):
    _,encoded=cv2.imencode('.png',scene())
    with pytest.raises(ValueError):enhance_frame(encoded.tobytes(),query)


def test_encoded_frame_ink_mode_produces_cropped_jpeg():
    _,encoded=cv2.imencode('.png',scene())
    output=enhance_frame(encoded.tobytes(),{'beta':['0'],'mode':['ink'],
        'roi':['.1,.125,.8,.75'],'strength':['75'],'tolerance':['20']})
    decoded=cv2.imdecode(np.frombuffer(output,np.uint8),cv2.IMREAD_COLOR)
    assert decoded.shape==(60,80,3)