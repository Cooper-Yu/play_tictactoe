"""Generate airborne XY tool paths without ROS IO or changing height/orientation."""
import copy
import math


def cross_path(start, size):
    """! @brief Return two diagonals with an explicit same-height transfer between them."""
    if not math.isfinite(size) or not 0 < size <= .1:
        raise ValueError('Cross size must be finite and in (0, 0.1] meters')
    points = [copy.deepcopy(start)]
    for dx, dy in [(size, size), (0., size), (size, 0.)]:
        pose = copy.deepcopy(start)
        pose.position.x += dx
        pose.position.y += dy
        points.append(pose)
    return points


def circle_path(start, radius, count=64):
    """! @brief Start on the left rim, trace one counterclockwise closed XY circle."""
    if not math.isfinite(radius) or not 0 < radius <= .04:
        raise ValueError('Circle radius must be finite and in (0, 0.04] meters')
    if not isinstance(count, int) or isinstance(count, bool) or not 16 <= count <= 256:
        raise ValueError('Circle sample count must be in 16..256')
    points = [copy.deepcopy(start)]
    for i in range(1, count):
        angle = math.pi + 2*math.pi*i/count
        pose = copy.deepcopy(start)
        pose.position.x += radius*(1+math.cos(angle))
        pose.position.y += radius*math.sin(angle)
        points.append(pose)
    points.append(copy.deepcopy(start))
    return points
