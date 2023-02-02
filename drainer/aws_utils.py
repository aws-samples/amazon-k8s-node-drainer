import logging

from botocore.exceptions import WaiterError

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def _find_instance_target_groups(elbv2, instance_id:str="") -> list:
    """Return all target groups (ELBv2) containing the instance identify by instance_id.
    """
    instance_tgs = set()

    tgs = elbv2.describe_target_groups()
    for tg in tgs["TargetGroups"]: 
        ths = elbv2.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
        for th in ths["TargetHealthDescriptions"]:
            if th["Target"]["Id"] == instance_id:
                if th["TargetHealth"]["State"] in ["healthy", "draining"]:
                    instance_tgs.add(tg["TargetGroupArn"])
                else:
                    logger.warning(f'{instance_id} is in {th["TargetHealth"]["State"]} state in target group {tg["TargetGroupName"]}')
    
    ret = list(instance_tgs)
    ret.sort()

    return ret

def _deregister_instance_from_target_groups(elbv2, instance_tgs:list=[], instance_id:str=""):
    """ Desregister an instance for all the target groups given in parameter. 
    Wait synchronously for target to be deregistered.
    """
    for tg_arn in instance_tgs:
        elbv2.deregister_targets(
            TargetGroupArn=tg_arn,
            Targets=[{"Id": instance_id}]
        )
    
    try:
        waiter = elbv2.get_waiter('target_deregistered')

        for tg_arn in instance_tgs:
            logger.info(f'Waiting for target_group {tg_arn} to deregister {instance_id}')
            waiter.wait(
                TargetGroupArn=tg_arn,
                WaiterConfig={  
                    # Waiting 2 min
                    'Delay': 10,
                    'MaxAttempts': 12
                }
            )

    except WaiterError as e:
        message = e.response["Message"]
        if "Max attempts exceeded" in message:
            logger.error(f'Took more than 2 min to deregister the mode : {message}')
        else:
            logger.error(message)


def deregister_and_drain_node(elbv2, instance_id:str="") -> None:
    """Deregister an instance from all the target groups is is into.
    """
    logger.info(f'Deregistering {instance_id} from all the target groups it is in')
    instance_tgs = _find_instance_target_groups(elbv2, instance_id)

    logger.info(f'Found {len(instance_tgs)} target groups for instance {instance_id}')
    _deregister_instance_from_target_groups(elbv2, instance_tgs, instance_id)

