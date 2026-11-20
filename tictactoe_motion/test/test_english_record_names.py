"""Preserve access to recorded system poses after changing their display language."""
import pytest
from tictactoe_motion.pose_recording.pose_recorder import PoseRecorder
from tictactoe_motion.pose_recording.record_names import LEGACY_RECORD_NAMES


@pytest.mark.parametrize('canonical,legacy', LEGACY_RECORD_NAMES.items())
def test_english_names_load_and_delete_legacy_records(tmp_path, canonical, legacy):
    recorder = PoseRecorder(tmp_path/'poses.json')
    recorder.poses[legacy] = {'name':legacy, 'value': [1]}
    record = recorder.get_pose(canonical)
    assert record['name'] == canonical
    record['value'].append(2)
    assert recorder.poses[legacy]['value'] == [1]
    recorder.delete_pose(canonical)
    assert not recorder.poses
