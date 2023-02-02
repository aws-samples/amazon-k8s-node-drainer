import tempfile
import boto3
import base64
import logging
import os.path
import re

from botocore.signers import RequestSigner

from aws_utils import deregister_and_drain_node
from eks_auth import eks_auth

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

REGION = os.environ['AWS_REGION']

elbv2 = boto3.client('elbv2', region_name=REGION)
asg = boto3.client('autoscaling', region_name=REGION)

def lambda_handler(event, _):

    lifecycle_hook_name = event['detail']['LifecycleHookName']
    auto_scaling_group_name = event['detail']['AutoScalingGroupName']
    instance_id = event['detail']['EC2InstanceId']
    
    deregister_and_drain_node(elbv2, instance_id)

    asg.complete_lifecycle_action(LifecycleHookName=lifecycle_hook_name,
                                    AutoScalingGroupName=auto_scaling_group_name,
                                    LifecycleActionResult='CONTINUE',
                                    InstanceId=instance_id)