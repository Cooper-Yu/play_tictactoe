"""Check the achieved end-effector pose against the configured tolerances."""

import math


def verify_pose_result(result, settings, *, require_orientation=True):
    angle = result.get('orientation_error_rad', float('inf'))
    result['passed'] = (
        result.get('passed', True)
        and result.get('position_error_m', float('inf')) <= settings['return_position_tolerance']
        and math.isfinite(angle)
        and (not require_orientation or angle <= settings['return_orientation_tolerance'])
    )
    assert result['passed'], result
    return result


def verify(driver, result, *, require_orientation=True):
    return verify_pose_result(
        result, driver.node.settings, require_orientation=require_orientation,
    )
