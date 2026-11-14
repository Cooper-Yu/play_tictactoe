from rclpy.node import Node
from sensor_msgs.msg import JointState
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from tf2_ros import TransformException
from geometry_msgs.msg import Pose
import rclpy

class MotionPlanner(Node):
    def __init__(self):
        super().__init__('motion_planner')
        self.current_joint_state = None
        self.joint_state_subscription = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_state_callback,
            10
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.state_timer = self.create_timer(1.0, self.report_current_state)

    def joint_state_callback(self, msg):
        self.current_joint_state = msg

    def get_current_pose(self):
        try:
            transform = self.tf_buffer.lookup_transform(
                'base_link',
                'link6',
                Time()
            )
            return transform
        except TransformException as error:
            self.get_logger().warning(f'unable to obtain the pose of link6: {error}')
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

        if axis == 'x':
            target_pose.position.x = target_pose.position.x + distance
        elif axis == 'y':
            target_pose.position.y = target_pose.position.y + distance
        elif axis == 'z':
            target_pose.position.z = target_pose.position.z + distance
        else:
            raise ValueError("axis must be 'x', 'y', 'z'")
        return target_pose

    def report_current_state(self):
        if self.current_joint_state is None:
            self.get_logger().info('Waiting for joint states')
            return
        joint_position = dict(zip(
            self.current_joint_state.name,
            self.current_joint_state.position
        ))
        required_joints = [f'joint{i}' for i in range(1,7)]
        if any(name not in joint_position for name in required_joints):
            self.get_logger().warning('Joint states are incomplete')
            return
        joint_summary = ', '.join(
            f'{name}={joint_position[name]:.4f}'
            for name in required_joints
        )
        self.get_logger().info(f'Joint positions (rad): {joint_summary}')
        transform = self.get_current_pose()
        if transform is None:
            return

        translation = transform.transform.translation
        orientation = transform.transform.rotation

        self.get_logger().info(
            f'link6 position (m): '
            f'x={translation.x:.4f}, '
            f'y={translation.y:.4f}, '
            f'z={translation.z:.4f}'
        )

        self.get_logger().info(
            f'link6 orientation (quaternion xyzw): '
            f'x={orientation.x:.4f}, '
            f'y={orientation.y:.4f}, '
            f'z={orientation.z:.4f}, '
            f'w={orientation.w:.4f}'
        )

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


if __name__ == '__main__':
    main()