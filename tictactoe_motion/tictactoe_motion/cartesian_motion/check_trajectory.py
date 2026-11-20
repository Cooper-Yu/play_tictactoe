"""Apply Cartesian trajectory checks and retry rules."""

from tictactoe_motion.trajectory_checks import JointExcursionError


def accept_linear(driver, *, allow_retry):
    try:
        driver.guard()
    except JointExcursionError:
        if not allow_retry:
            raise
        driver.node.invalidate_plan()
        return False
    return True


def accept_path(driver, excursion_limit, *, allow_retry):
    driver.check_motion_guard()
    if allow_retry and driver.node.planned_trajectory is None:
        report = driver.node.cartesian_planner.last_report or {}
        reason = report.get('reason', '')
        if reason.startswith((
            'Incomplete Cartesian path:', 'FK path deviation:',
            'Cartesian joint jump exceeds limit',
        )):
            return False
    try:
        driver.guard(excursion_limit)
    except JointExcursionError:
        if not allow_retry:
            raise
        driver.node.invalidate_plan()
        return False
    return True
