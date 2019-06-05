import logging
import time

from kubernetes.client.rest import ApiException

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


def remove_all_pods(api, node_name, poll=5):
    """Removes all Kubernetes pods from the specified node."""
    field_selector = 'spec.nodeName=' + node_name
    pods = api.list_pod_for_all_namespaces(watch=False, field_selector=field_selector)

    logger.debug('Number of pods to delete: ' + str(len(pods.items)))

    try_until_completed(api, evict_pods, pods, poll)
    try_until_completed(api, get_pending, pods, poll)


def try_until_completed(api, action, pods, poll):
    pending = pods.items
    while len(pending) > 0:
        pending = action(api, pending)
        if (len(pending)) <= 0:
            return
        time.sleep(poll)


def evict_pods(api, pods):
    remaining = []
    for pod in pods:
        logger.info('Evicting pod {} in namespace {}'.format(pod.metadata.name, pod.metadata.namespace))
        body = {
            'apiVersion': 'policy/v1beta1',
            'kind': 'Eviction',
            'deleteOptions': {},
            'metadata': {
                'name': pod.metadata.name,
                'namespace': pod.metadata.namespace
            }
        }
        try:
            api.create_namespaced_pod_eviction(pod.metadata.name + '-eviction', pod.metadata.namespace, body)
        except ApiException as err:
            if err.status == 429:
                remaining.append(pod)
                logger.warning("Pod %s in namespace %s could not be evicted due to disruption budget. Will retry.", pod.metadata.name, pod.metadata.namespace)
            else:
                logger.exception("Unexpected error adding eviction for pod %s in namespace %s", pod.metadata.name, pod.metadata.namespace)
        except:
            logger.exception("Unexpected error adding eviction for pod %s in namespace %s", pod.metadata.name, pod.metadata.namespace)
    return remaining


def get_pending(api, pods):
    pending = []
    for old_pod in pods:
        try:
            current_pod = api.read_namespaced_pod(old_pod.metadata.name, old_pod.metadata.namespace)
            if current_pod.metadata.uid == old_pod.metadata.uid:
                logger.debug("Pod %s in namespace %s is still awaiting deletion", old_pod.metadata.name, old_pod.metadata.namespace)
                pending.append(old_pod)
            else:
                logger.info("Eviction successful: %s in namespace %s", old_pod.metadata.name, old_pod.metadata.namespace)
        except ApiException as err:
            if err.status == 404:
                logger.info("Eviction successful: %s in namespace %s", old_pod.metadata.name, old_pod.metadata.namespace)
            else:
                pending.append(old_pod)
                logger.exception("Unexpected error waiting for pod %s in namespace %s", old_pod.metadata.name, old_pod.metadata.namespace)
        except:
            logger.exception("Unexpected error waiting for pod %s in namespace %s", old_pod.metadata.name, old_pod.metadata.namespace)
            pending.append(old_pod)
    return pending


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
