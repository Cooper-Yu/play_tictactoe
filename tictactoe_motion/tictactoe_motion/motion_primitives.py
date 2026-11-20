"""Compatibility imports for the three basic motion types."""

from .cartesian_motion import CartesianMotion
from .cartesian_motion.check_trajectory import JointExcursionError
from .joint_motion import JointMotion
from .pose_motion import PoseMotion

__all__ = ['CartesianMotion', 'JointExcursionError', 'JointMotion', 'PoseMotion']
