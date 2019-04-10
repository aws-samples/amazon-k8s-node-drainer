import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def cordon_node(api, node_name):
    """Marks the specified node as unschedulable, which means that no new pods can be launched on the
    node by the Kubernetes scheduler.
    """
    patch_body = {
        'apiVersion': 'v1',
        'kind': 'Node',
        'metadata': {
            'name': node_name
        },
        'spec': {
            'unschedulable': True
        }
    }

    api.patch_node(node_name, patch_body)


def remove_all_pods(api, node_name):
    """Removes all Kubernetes pods from the specified node."""
    field_selector = 'spec.nodeName=' + node_name
    pods = api.list_pod_for_all_namespaces(watch=False, field_selector=field_selector)

    logger.debug('Number of pods to delete: ' + str(len(pods.items)))

    for pod in pods.items:
        logger.info('Deleting pod {} in namespace {}'.format(pod.metadata.name, pod.metadata.namespace))
        body = {
            'apiVersion': 'policy/v1beta1',
            'kind': 'Eviction',
            'metadata': {
                'name': pod.metadata.name,
                'namespace': pod.metadata.namespace
            }
        }
        api.create_namespaced_pod_eviction(pod.metadata.name + '-eviction', pod.metadata.namespace, body)


def node_exists(api, node_name):
    """Determines whether the specified node is still part of the cluster."""
    nodes = api.list_node(include_uninitialized=True, pretty=True).items
    node = next((n for n in nodes if n.metadata.name == node_name), None)
    return False if not node else True


def abandon_lifecycle_action(asg_client, auto_scaling_group_name, lifecycle_hook_name, instance_id):
    """Completes the lifecycle action with the ABANDON result, which stops any remaining actions,
    such as other lifecycle hooks.
    """
    asg_client.complete_lifecycle_action(LifecycleHookName=lifecycle_hook_name,
                                         AutoScalingGroupName=auto_scaling_group_name,
                                         LifecycleActionResult='ABANDON',
                                         InstanceId=instance_id)
