import boto3
import base64
import logging
import os.path
import re
import yaml
import json
import time

from botocore.signers import RequestSigner
import kubernetes as k8s
from kubernetes.client.rest import ApiException

from k8s_utils import (
    abandon_lifecycle_action,
    cordon_node,
    node_exists,
    remove_all_pods,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

KUBE_FILEPATH = "/tmp/kubeconfig"
CLUSTER_NAME = os.environ["CLUSTER_NAME"]
REGION = os.environ["AWS_REGION"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
CFN_STACK_NAME = os.environ["CFN_STACK_NAME"]
CFN_RESOURCE_ID = os.environ["CFN_RESOURCE_ID"]

eks = boto3.client("eks", region_name=REGION)
ec2 = boto3.client("ec2", region_name=REGION)
asg = boto3.client("autoscaling", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)
cfn = boto3.client("cloudformation", region_name=REGION)


def proccess_queue():
    """Receive and delete message from SQS queue.

    Returns:
        SQS message
    """

    response = sqs.receive_message(
        QueueUrl=SQS_QUEUE_URL,
        AttributeNames=["SentTimestamp"],
        MaxNumberOfMessages=1,
        MessageAttributeNames=["All"],
        VisibilityTimeout=30,
        WaitTimeSeconds=0,
    )

    if not response.get("Messages"):
        raise Exception(
            "SQS message not found. Lambda will be restarted by ASG terminating lifecycle hook."
        )
    else:
        message = response["Messages"][0]
        receipt_handle = message["ReceiptHandle"]

        sqs.delete_message(QueueUrl=SQS_QUEUE_URL, ReceiptHandle=receipt_handle)
        return message


def launching_lifecycle_action(api, message, poll=5):
    """Complete ASG lifecycle action launching instance.
       Check launching node readiness in the Kubernetes control plane.

    Args:
        api (object): Kubernetes API client object.
        message (list): SQS message with lainching instance metadate.
        poll (int): Interval for retries.

    Returns:
        EC2 launching instance id
    """
    body = json.loads(message["Body"])

    # Send the result ec2 launching lifecycle hook
    lifecycle_hook_name = body["LifecycleHookName"]
    auto_scaling_group_name = body["AutoScalingGroupName"]

    ec2_launch_id = body["EC2InstanceId"]

    asg.complete_lifecycle_action(
        LifecycleHookName=lifecycle_hook_name,
        AutoScalingGroupName=auto_scaling_group_name,
        LifecycleActionResult="CONTINUE",
        InstanceId=ec2_launch_id,
    )
    # Status EC2 launch
    instance_launch = ec2.describe_instances(InstanceIds=[ec2_launch_id])[
        "Reservations"
    ][0]["Instances"][0]

    node_name_launch = instance_launch["PrivateDnsName"]
    logger.info("Node name LAUNCHING: " + node_name_launch)

    while not node_exists(api, node_name_launch):
        logger.debug(
            "Still waiting for a new LAUNCHING Node is a part of the cluster: "
            + node_name_launch
        )
        time.sleep(poll)

    while True:
        ec2_launch_status = api.read_node_status(node_name_launch, pretty=True)
        ready_condition = next(
            filter(
                lambda condition: condition.type == "Ready",
                ec2_launch_status.status.conditions,
            )
        )
        if ready_condition.status == "True":
            logger.info(
                "Node LAUNCHING is ready: {0.status}, reason - {0.reason}".format(
                    ready_condition
                )
            )
            return ec2_launch_id
        logger.debug("Still waiting for a new LAUNCHING Node: " + node_name_launch)
        time.sleep(poll)


def cfn_stack_signal(ec2_launch_id, status):
    """Send CloudFormation Signal Resource."""
    cfn_signal_stack = cfn.signal_resource(
        StackName=CFN_STACK_NAME,
        LogicalResourceId=CFN_RESOURCE_ID,
        UniqueId=ec2_launch_id,
        Status=status,
    )


def create_kube_config(eks):
    """Creates the Kubernetes config file required when instantiating the API client."""
    cluster_info = eks.describe_cluster(name=CLUSTER_NAME)["cluster"]
    certificate = cluster_info["certificateAuthority"]["data"]
    endpoint = cluster_info["endpoint"]

    kube_config = {
        "apiVersion": "v1",
        "clusters": [
            {
                "cluster": {
                    "server": endpoint,
                    "certificate-authority-data": certificate,
                },
                "name": "k8s",
            }
        ],
        "contexts": [{"context": {"cluster": "k8s", "user": "aws"}, "name": "aws"}],
        "current-context": "aws",
        "Kind": "config",
        "users": [{"name": "aws", "user": "lambda"}],
    }

    with open(KUBE_FILEPATH, "w") as f:
        yaml.dump(kube_config, f, default_flow_style=False)


def get_bearer_token(cluster, region):
    """Creates the authentication to token required by AWS IAM Authenticator. This is
    done by creating a base64 encoded string which represents a HTTP call to the STS
    GetCallerIdentity Query Request (https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html).
    The AWS IAM Authenticator decodes the base64 string and makes the request on behalf of the user.
    """
    STS_TOKEN_EXPIRES_IN = 60
    session = boto3.session.Session()

    client = session.client("sts", region_name=region)
    service_id = client.meta.service_model.service_id

    signer = RequestSigner(
        service_id, region, "sts", "v4", session.get_credentials(), session.events
    )

    params = {
        "method": "GET",
        "url": "https://sts.{}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15".format(
            region
        ),
        "body": {},
        "headers": {"x-k8s-aws-id": cluster},
        "context": {},
    }

    signed_url = signer.generate_presigned_url(
        params, region_name=region, expires_in=STS_TOKEN_EXPIRES_IN, operation_name=""
    )

    base64_url = base64.urlsafe_b64encode(signed_url.encode("utf-8")).decode("utf-8")

    # need to remove base64 encoding padding:
    # https://github.com/kubernetes-sigs/aws-iam-authenticator/issues/202
    return "k8s-aws-v1." + re.sub(r"=*", "", base64_url)


def _lambda_handler(k8s_config, k8s_client, event, queue_result):
    if not os.path.exists(KUBE_FILEPATH):
        logger.info("No kubeconfig file found. Generating...")
        create_kube_config(eks)

    lifecycle_hook_name_terminating = event["detail"]["LifecycleHookName"]
    auto_scaling_group_name = event["detail"]["AutoScalingGroupName"]

    instance_id = event["detail"]["EC2InstanceId"]
    instance = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0][
        "Instances"
    ][0]

    node_name = instance["PrivateDnsName"]
    logger.info("Node name TERMINATING: " + node_name)

    # Configure
    k8s_config.load_kube_config(KUBE_FILEPATH)
    configuration = k8s_client.Configuration()
    configuration.api_key["authorization"] = get_bearer_token(CLUSTER_NAME, REGION)
    configuration.api_key_prefix["authorization"] = "Bearer"
    # API
    api = k8s_client.ApiClient(configuration)
    v1 = k8s_client.CoreV1Api(api)

    ec2_new_launching = None

    try:
        ec2_new_launching = launching_lifecycle_action(v1, queue_result)

        if not node_exists(v1, node_name):
            logger.error("Node not found.")
            abandon_lifecycle_action(
                asg,
                auto_scaling_group_name,
                lifecycle_hook_name_terminating,
                instance_id,
            )
            cfn_stack_signal(ec2_new_launching, "FAILURE")
            return

        cordon_node(v1, node_name)

        remove_all_pods(v1, node_name)

        asg.complete_lifecycle_action(
            LifecycleHookName=lifecycle_hook_name_terminating,
            AutoScalingGroupName=auto_scaling_group_name,
            LifecycleActionResult="CONTINUE",
            InstanceId=instance_id,
        )

        cfn_stack_signal(ec2_new_launching, "SUCCESS")

    except ApiException:
        logger.exception(
            "There was an error removing the pods from the node {}".format(node_name)
        )
        abandon_lifecycle_action(
            asg, auto_scaling_group_name, lifecycle_hook_name_terminating, instance_id
        )
        if ec2_new_launching:
            cfn_stack_signal(ec2_new_launching, "FAILURE")


def lambda_handler(event, _):
    # Validate received SQS message
    check_key = None
    process_queue_result = True
    while not check_key and process_queue_result:
        process_queue_result = proccess_queue()
        if not process_queue_result:
            continue
        # Parse SQS message
        body = json.loads(process_queue_result["Body"])
        check_key = body.get("LifecycleTransition")

    if process_queue_result:
        return _lambda_handler(k8s.config, k8s.client, event, process_queue_result)
