"""Compatibility imports for the three basic motion types."""

from .cartesian_motion import CartesianMotion
from .joint_motion import JointMotion
from .pose_motion import PoseMotion
from .trajectory_checks import JointExcursionError

__all__ = ['CartesianMotion', 'JointExcursionError', 'JointMotion', 'PoseMotion']
