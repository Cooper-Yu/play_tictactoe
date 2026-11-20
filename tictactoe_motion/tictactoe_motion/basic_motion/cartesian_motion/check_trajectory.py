"""Apply Cartesian trajectory checks and retry rules."""

from tictactoe_motion.trajectory_motion.trajectory_checks import JointExcursionError


def accept_linear(driver, *, allow_retry, limit=.5):
    try:
        if limit == .5:
            driver.guard()
        else:
            driver.guard(limit)
    except JointExcursionError as error:
        if not allow_retry:
            raise
        planner = getattr(driver.node, "cartesian_planner", None)
        if planner is not None:
            planner.last_report = {"accepted": False, "reason": str(error)}
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
    except JointExcursionError as error:
        if not allow_retry:
            raise
        planner = getattr(driver.node, "cartesian_planner", None)
        if planner is not None:
            planner.last_report = {"accepted": False, "reason": str(error)}
        driver.node.invalidate_plan()
        return False
    return True
