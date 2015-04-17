#! /usr/bin/env python
import rospy
import smach
import tf

import ed.msg
import robot_skills.util.msg_constructors as msgs
import robot_skills.util.transformations as transformations

from robot_skills.arms import Arm
from robot_smach_states.state import State
from robot_smach_states.util.designators import check_type

from robot_smach_states.navigation import NavigateToGrasp


class PickUp(State):
    def __init__(self, robot, arm, grab_entity):
        # Check that the entity_designator resolves to an Entity or is an entity
        check_type(grab_entity, ed.msg.EntityInfo)

        # Check that the arm is a designator that resolves to an Arm or is an Arm
        check_type(arm, Arm)

        State.__init__(self, locals(), outcomes=['succeeded', 'failed'])

    def run(self, robot, arm, grab_entity):
        if not grab_entity:
            rospy.logerr("Could not resolve grab_entity")
            return "failed"
        if not arm:
            rospy.logerr("Could not resolve arm")
            return "failed"

        rospy.loginfo('PickUp!')

        # goal in map frame
        goal_map = msgs.Point(0, 0, 0)

        try:
            # Transform to base link frame
            goal_bl = transformations.tf_transform(
                goal_map, grab_entity.id, robot.robot_name+'/base_link',
                tf_listener=robot.tf_listener
            )
            if goal_bl is None:
                rospy.logerr('Transformation of goal to base failed')
                return 'failed'
        except tf.Exception, tfe:
            rospy.logerr('Transformation of goal to base failed: {0}'.format(tfe))
            return 'failed'

        rospy.loginfo(goal_bl)

        # Carrying pose
        if arm.side == 'left':
            y_home = 0.3
        else:
            y_home = -0.3

        # immediately go to the retract pos
        rospy.loginfo('y_home = ' + str(y_home))
        rospy.loginfo('start moving to a good pregrasp position')
        if not arm.send_goal(0.25,         y_home,       goal_bl.z + 0.1,
                             float('nan'), float('nan'), float('nan'),
                             timeout=60):
            rospy.logerr('Failed pregrasp pose')

        # Open gripper
        arm.send_gripper_goal('open')

        # Pre-grasp
        rospy.loginfo('Starting Pre-grasp')
        if not arm.send_goal(goal_bl.x,    goal_bl.y,    goal_bl.z,
                             0,    0,      float('nan'),
                             frame_id='/'+robot.robot_name+'/base_link',
                             timeout=60, pre_grasp=True, first_joint_pos_only=True
                             ):
            rospy.logerr('Pre-grasp failed:')

            arm.reset()
            arm.send_gripper_goal('close', timeout=None)
            return 'failed'

        # Grasp
        rospy.loginfo('Starting Grasp')
        if not arm.send_goal(goal_bl.x,    goal_bl.y,    goal_bl.z,
                             0,    0,      float('nan'),
                             frame_id='/'+robot.robot_name+'/base_link',
                             timeout=60, pre_grasp=True,
                             allowed_touch_objects=[grab_entity.id]
                             ):
            robot.speech.speak('I am sorry but I cannot move my arm to the object position', block=False)
            rospy.logerr('Grasp failed')
            arm.reset()
            arm.send_gripper_goal('close', timeout=None)
            return 'failed'

        # Close gripper
        arm.send_gripper_goal('close')

        arm.occupied_by = grab_entity

        # Lift
        rospy.loginfo('Starting Lift')
        if not arm.send_goal(goal_bl.x,    goal_bl.y,    goal_bl.z,
                             0,    0,      float('nan'),
                             frame_id='/'+robot.robot_name+'/base_link',
                             timeout=60, allowed_touch_objects=[grab_entity.id]
                             ):
            rospy.logerr('Failed Lift')

        # Retract
        rospy.loginfo('Starting Retract')
        if not arm.send_goal(goal_bl.x - 0.1, goal_bl.y,    goal_bl.z + 0.1,
                             0,    0,      float('nan'),
                             frame_id='/'+robot.robot_name+'/base_link',
                             timeout=60, allowed_touch_objects=[grab_entity.id]
                             ):
            rospy.logerr('Failed retract')

        rospy.loginfo('y_home = ' + str(y_home))

        rospy.loginfo('start moving to carrying pose')
        if not arm.send_goal(0.25, y_home, float('nan'),
                             0,    0,      float('nan'),
                             timeout=60
                             ):
            rospy.logerr('Failed carrying pose')

        return 'succeeded'


class Grab(smach.StateMachine):
    def __init__(self, robot, item, arm):
        smach.StateMachine.__init__(self, outcomes=['done', 'failed'])

        # Check types or designator resolve types
        check_type(item, ed.msg.EntityInfo)
        check_type(arm, Arm)

        with self:
            smach.StateMachine.add('NAVIGATE_TO_GRAB', NavigateToGrasp(robot, item, arm),
                                   transitions={'unreachable':      'failed',
                                                'goal_not_defined': 'failed',
                                                'arrived':          'GRAB'})

            smach.StateMachine.add('GRAB', PickUp(robot, arm, item),
                                   transitions={'succeeded': 'done',
                                                'failed':    'failed'})
