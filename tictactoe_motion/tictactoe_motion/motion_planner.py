from rclpy.node import Node
from sensor_msgs.msg import JointState
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from tf2_ros import TransformException
from geometry_msgs.msg import Pose
import rclpy
from moveit_msgs.action import MoveGroup
from shape_msgs.msg import SolidPrimitive
from moveit_msgs.msg import PositionConstraint, OrientationConstraint, Constraints
from rclpy.action import ActionClient
from action_msgs.msg import GoalStatus
from moveit_msgs.msg import MoveItErrorCodes

class MotionPlanner(Node):
    def __init__(self):
        super().__init__("motion_planner")
        self.current_joint_state = None
        self.joint_state_subscription = self.create_subscription(
            JointState, "/joint_states", self.joint_state_callback, 10
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.state_timer = self.create_timer(1.0, self.report_current_state)

        self.move_client = ActionClient(self, MoveGroup, "/move_action")

        self.demo_timer = self.create_timer(3.0, self.run_planning_demo)

    def joint_state_callback(self, msg):
        self.current_joint_state = msg

    def get_current_pose(self):
        try:
            transform = self.tf_buffer.lookup_transform("base_link", "link6", Time())
            return transform
        except TransformException as error:
            self.get_logger().warning(f"unable to obtain the pose of link6: {error}")
            return None

    def calculate_target_pose(self, current_transform, axis, distance):
        target_pose = Pose()
        translation = current_transform.transform.translation

        target_pose.position.x = translation.x
        target_pose.position.y = translation.y
        target_pose.position.z = translation.z

        rotation = current_transform.transform.rotation

        target_pose.orientation.x = rotation.x
        target_pose.orientation.y = rotation.y
        target_pose.orientation.z = rotation.z
        target_pose.orientation.w = rotation.w

        if axis == "x":
            target_pose.position.x = target_pose.position.x + distance
        elif axis == "y":
            target_pose.position.y = target_pose.position.y + distance
        elif axis == "z":
            target_pose.position.z = target_pose.position.z + distance
        else:
            raise ValueError("axis must be 'x', 'y', 'z'")
        return target_pose

    def report_current_state(self):
        if self.current_joint_state is None:
            self.get_logger().info("Waiting for joint states")
            return
        joint_position = dict(
            zip(self.current_joint_state.name, self.current_joint_state.position)
        )
        required_joints = [f"joint{i}" for i in range(1, 7)]
        if any(name not in joint_position for name in required_joints):
            self.get_logger().warning("Joint states are incomplete")
            return
        joint_summary = ", ".join(
            f"{name}={joint_position[name]:.4f}" for name in required_joints
        )
        self.get_logger().info(f"Joint positions (rad): {joint_summary}")
        transform = self.get_current_pose()
        if transform is None:
            return

        translation = transform.transform.translation
        orientation = transform.transform.rotation

        self.get_logger().info(
            f"link6 position (m): "
            f"x={translation.x:.4f}, "
            f"y={translation.y:.4f}, "
            f"z={translation.z:.4f}"
        )

        self.get_logger().info(
            f"link6 orientation (quaternion xyzw): "
            f"x={orientation.x:.4f}, "
            f"y={orientation.y:.4f}, "
            f"z={orientation.z:.4f}, "
            f"w={orientation.w:.4f}"
        )

    def build_planning_goal(self, target_pose, current_joint_state):
        goal = MoveGroup.Goal()

        goal.request.group_name = "arm"
        goal.request.allowed_planning_time = 5.0
        goal.request.max_velocity_scaling_factor = 0.1
        goal.request.max_acceleration_scaling_factor = 0.1

        goal.request.start_state.joint_state = current_joint_state
        goal.request.start_state.is_diff = True

        position_constraint = PositionConstraint()
        position_constraint.header.frame_id = "base_link"
        position_constraint.link_name = "link6"
        position_constraint.weight = 1.0

        region = SolidPrimitive()
        region.type = SolidPrimitive.SPHERE
        region.dimensions = [0.0001]

        region_pose = Pose()
        region_pose.position = target_pose.position
        region_pose.orientation.w = 1.0

        position_constraint.constraint_region.primitives = [region]
        position_constraint.constraint_region.primitive_poses = [region_pose]

        orientation_constraint = OrientationConstraint()
        orientation_constraint.header.frame_id = "base_link"
        orientation_constraint.link_name = "link6"
        orientation_constraint.orientation = target_pose.orientation

        orientation_constraint.absolute_x_axis_tolerance = 0.01
        orientation_constraint.absolute_y_axis_tolerance = 0.01
        orientation_constraint.absolute_z_axis_tolerance = 0.01
        orientation_constraint.weight = 1.0

        target_constraints = Constraints()
        target_constraints.position_constraints = [position_constraint]
        target_constraints.orientation_constraints = [orientation_constraint]

        goal.request.goal_constraints = [target_constraints]

        goal.planning_options.plan_only = True
        return goal

    def request_plan(self, axis, distance):
        if self.current_joint_state is None:
            self.get_logger().warning("Cannot plan: joint states unavailable")
            return
        current_transform = self.get_current_pose()
        if current_transform is None:
            return
        target_pose = self.calculate_target_pose(current_transform, axis, distance)
        goal = self.build_planning_goal(target_pose, self.current_joint_state)
        if not self.move_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().warning("MoveIt action server unavailable")
            return
        self.send_goal_future = self.move_client.send_goal_async(goal)
        self.send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warning("Planning goal rejected")
            return
        self.get_logger().info("Planning goal accepted")
        self.result_future = goal_handle.get_result_async()
        self.result_future.add_done_callback(self.planning_result_callback)

    def planning_result_callback(self, future):
        response = future.result()
        status = response.status
        result = response.result

        if status == GoalStatus.STATUS_SUCCEEDED and result.error_code.val == MoveItErrorCodes.SUCCESS:
            self.get_logger().info('Planning succeeded')
            self.planned_trajectory = result.planned_trajectory
            joint_trajectory = self.planned_trajectory.joint_trajectory

            self.get_logger().info(
                f'Planned joints: {list(joint_trajectory.joint_names)}, '
                f'trajectory points: {len(joint_trajectory.points)}'
            )
        else:
            self.get_logger().warning(
                f'Planning failed: status={status}, '
                f'MoveIt error code={result.error_code.val}'
            )
    def run_planning_demo(self):
        self.demo_timer.cancel()
        self.request_plan('x', 0.001)

def main(args=None):
    rclpy.init(args=args)
    node = MotionPlanner()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
