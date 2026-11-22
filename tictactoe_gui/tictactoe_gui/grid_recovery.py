"""Recover only the unstarted suffix of a verified grid stroke sequence."""
import copy
import re


def unstarted_grid_tail(strokes, workstation, accepted_job):
    """Reject partially drawn or segmented strokes instead of replaying unknown ink."""
    progress = workstation.get('drawing_progress') or {}
    count = progress.get('completed_input_strokes')
    stage = re.fullmatch(r'(\d+)_(lower|transfer|lift)', progress.get('stage', ''))
    if (not isinstance(strokes, list) or type(count) is not int
            or not 0 <= count < len(strokes) or workstation.get('job') != accepted_job
            or progress.get('shape') != 'canvas'
            or progress.get('total_input_strokes') != len(strokes)
            or progress.get('source_stroke') != count+1
            or progress.get('completed_parts') != count
            or stage is None or int(stage[1]) != count+1):
        raise RuntimeError('Grid interruption is not an unstarted stroke; inspect before rebuilding')
    if stage[2] == 'lift':
        # run_strokes enters this exact stage only after a verified full draw.
        # Require measured clearance; never reuse a partially completed lift.
        pose = workstation.get('pose') or {}
        if (workstation.get('busy') or not workstation.get('fresh')
                or not isinstance(pose.get('z'), (int, float))
                or not .2109 <= pose['z'] <= .217
                or progress.get('total_parts') != len(strokes)):
            raise RuntimeError('Completed grid draw needs fresh raised-pen confirmation')
        count += 1
    return copy.deepcopy(strokes[count:]), count
