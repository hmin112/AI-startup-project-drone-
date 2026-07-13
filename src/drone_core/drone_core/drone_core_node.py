import json
import threading

import rclpy
import tf2_ros
from geometry_msgs.msg import PoseStamped, TransformStamped
from mavros_msgs.msg import State
from mavros_msgs.srv import CommandBool, SetMode
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String


class DroneCoreNode(Node):
    """MAVROS 통신, FC 제어 및 비행 상태 모니터링을 담당하는 노드."""

    def __init__(self):
        super().__init__('drone_core_node')

        self.declare_parameter('setpoint_rate_hz', 20.0)

        self._lock = threading.Lock()
        self._state = State()
        self._battery = BatteryState()
        self._current_pose = PoseStamped()
        self._target_pose = None  # None이면 현재 위치를 그대로 유지(hold)
        self._tf_broadcaster = tf2_ros.TransformBroadcaster(self)

        mavros_qos = QoSProfile(depth=10, reliability=QoSReliabilityPolicy.BEST_EFFORT)

        self.create_subscription(State, '/mavros/state', self._on_state, mavros_qos)
        self.create_subscription(
            PoseStamped, '/mavros/local_position/pose', self._on_local_position, mavros_qos
        )
        self.create_subscription(BatteryState, '/mavros/battery', self._on_battery, mavros_qos)

        self._setpoint_pub = self.create_publisher(PoseStamped, '/mavros/setpoint_position/local', 10)
        self._status_pub = self.create_publisher(String, '/drone_core/status', 10)

        self._arming_client = self.create_client(CommandBool, '/mavros/cmd/arming')
        self._set_mode_client = self.create_client(SetMode, '/mavros/set_mode')

        setpoint_rate_hz = self.get_parameter('setpoint_rate_hz').value
        self.create_timer(1.0 / setpoint_rate_hz, self._publish_setpoint)
        self.create_timer(1.0, self._publish_status)

        self.get_logger().info('drone_core_node started')

    def _on_state(self, msg):
        with self._lock:
            self._state = msg

    def _on_local_position(self, msg):
        with self._lock:
            self._current_pose = msg
        # slam_toolbox는 odom->base_link를 독립적인 오도메트리 소스로 기대하고
        # 그 위에 스캔매칭으로 map->odom 보정을 얹는다. GPS 음영구역(교량 하부)
        # 대응을 위해 이 오도메트리는 FC 자체 EKF(local_position/pose, GPS 없이도
        # IMU/광류/거리센서 등으로 로컬 추정)를 그대로 쓴다.
        self._broadcast_odom_tf(msg)

    def _broadcast_odom_tf(self, pose: PoseStamped):
        transform = TransformStamped()
        transform.header.stamp = pose.header.stamp
        transform.header.frame_id = 'odom'
        transform.child_frame_id = 'base_link'
        transform.transform.translation.x = pose.pose.position.x
        transform.transform.translation.y = pose.pose.position.y
        transform.transform.translation.z = pose.pose.position.z
        transform.transform.rotation = pose.pose.orientation
        self._tf_broadcaster.sendTransform(transform)

    def _on_battery(self, msg):
        with self._lock:
            self._battery = msg

    def set_target_pose(self, pose: PoseStamped):
        """오프보드 setpoint 목표 갱신. 미션 로직(추후 구현)에서 호출."""
        with self._lock:
            self._target_pose = pose

    def _publish_setpoint(self):
        # PX4 OFFBOARD 모드는 setpoint가 일정 주기 이상 계속 발행돼야 유지되고,
        # 스트림이 끊기면 자동으로 이전 모드로 폴백한다. 목표가 없으면 마지막으로
        # 알려진 현재 위치를 그대로 다시 보내 제자리 유지(hold)한다.
        with self._lock:
            pose = self._target_pose or self._current_pose
        pose.header.stamp = self.get_clock().now().to_msg()
        self._setpoint_pub.publish(pose)

    def _publish_status(self):
        with self._lock:
            state, battery = self._state, self._battery
        status = {
            'connected': state.connected,
            'armed': state.armed,
            'mode': state.mode,
            'battery_percentage': battery.percentage,
        }
        self._status_pub.publish(String(data=json.dumps(status)))

    def arm(self, value: bool = True):
        """/mavros/cmd/arming 서비스 호출 (비동기, Future 반환)."""
        if not self._arming_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn('arming service unavailable')
            return None
        request = CommandBool.Request()
        request.value = value
        return self._arming_client.call_async(request)

    def set_mode(self, mode: str):
        """/mavros/set_mode 서비스 호출 (비동기, Future 반환)."""
        if not self._set_mode_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().warn('set_mode service unavailable')
            return None
        request = SetMode.Request()
        request.custom_mode = mode
        return self._set_mode_client.call_async(request)


def main(args=None):
    rclpy.init(args=args)
    node = DroneCoreNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
