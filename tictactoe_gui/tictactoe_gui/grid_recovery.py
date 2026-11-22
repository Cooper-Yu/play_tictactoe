"""Recover only the unstarted suffix of a verified grid stroke sequence."""
import copy
import re


def unstarted_grid_tail(strokes, workstation, accepted_job):
    """Reject partially drawn or segmented strokes instead of replaying unknown ink."""
    progress = workstation.get('drawing_progress') or {}
    count = progress.get('completed_input_strokes')
    if (not isinstance(strokes, list) or type(count) is not int
            or not 0 <= count < len(strokes) or workstation.get('job') != accepted_job
            or progress.get('shape') != 'canvas'
            or progress.get('total_input_strokes') != len(strokes)
            or progress.get('source_stroke') != count+1
            or progress.get('completed_parts') != count
            or not re.fullmatch(r'\d+_(?:lower|transfer)', progress.get('stage', ''))):
        raise RuntimeError('Grid interruption is not an unstarted stroke; inspect before rebuilding')
    return copy.deepcopy(strokes[count:]), count
