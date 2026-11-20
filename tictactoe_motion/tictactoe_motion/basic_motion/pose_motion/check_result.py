"""Check the achieved end-effector pose against the configured tolerances."""


def verify_pose_result(result, settings):
    result['passed'] = (
        result.get('passed', True)
        and result.get('position_error_m', float('inf')) <= settings['return_position_tolerance']
        and result.get('orientation_error_rad', float('inf')) <= settings['return_orientation_tolerance']
    )
    assert result['passed'], result
    return result


def verify(driver, result):
    return verify_pose_result(result, driver.node.settings)
