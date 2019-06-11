[![Build Status](https://travis-ci.org/aws-samples/amazon-k8s-node-drainer.svg?branch=master)](https://travis-ci.org/aws-samples/amazon-k8s-node-drainer)

# Amazon EKS Node Drainer

This sample code provides a means to gracefully terminate nodes of an Amazon Elastic Container Service for Kubernetes 
(Amazon EKS) cluster when managed as part of an Amazon EC2 Auto Scaling Group.

The code provides an AWS Lambda function that integrates as an [Amazon EC2 Auto
Scaling Lifecycle Hook](https://docs.aws.amazon.com/autoscaling/ec2/userguide/lifecycle-hooks.html).
When called, the Lambda function calls the Kubernetes API to cordon and evict all evictable pods from the node being 
terminated. It will then wait until all pods have been evicted before the Auto Scaling group continues to terminate the
EC2 instance. The lambda may be killed by the function timeout before all evictions complete successfully, in which case
the lifecycle hook may re-execute the lambda to try again. If the lifecycle heartbeat expires then termination of the EC2
instance will continue regardless of whether or not draining was successful. You may need to increase the function and
heartbeat timeouts in template.yaml if you have very long grace periods.

Using this approach can minimise disruption to the services running in your cluster by allowing Kubernetes to 
reschedule the pod prior to the instance being terminated enters the TERMINATING state. It works by using 
[Amazon EC2 Auto Scaling Lifecycle Hooks](https://docs.aws.amazon.com/autoscaling/ec2/userguide/lifecycle-hooks.html)
to trigger an AWS Lambda function that uses the Kubernetes API to cordon the node and evict the pods.

NB: The lambda function created assumes that the Amazon EKS cluster's Kubernetes API server endpoint has public access 
enabled, if your endpoint only has private access enabled then you must modify the `template.yml` file to ensure the 
lambda function is running in the correct VPC and subnet.

Below is a brief explanation of the folder structure of the project:

```bash
.
├── README.md                   <-- This instructions file
├── build_deploy.sh             <-- Deployment script
├── drainer                     <-- Source code for the lambda function
│   ├── __init__.py
│   ├── drainer.py              <-- Lambda function code
│   ├── requirements.txt        <-- Lambda Python dependencies
│   ├── k8s_utils.py
├── k8s_rbac/                   <-- Kubernetes RBAC configuration
├── template.yaml               <-- SAM Template
└── tests                       <-- Unit tests
    └── drainer
        ├── __init__.py
        └── test_handler.py
```

## Requirements

* [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
* AWS CLI already configured with Administrator permission
* [Python 3](https://www.python.org/downloads/)
* [Docker](https://www.docker.com/community-edition)
* [Pipenv](https://pipenv.readthedocs.io/en/latest/) (Only if you wish to run the tests)

## Setup process

### Local development

**Invoking function locally using a local sample payload**

```bash
sam local invoke DrainerFunction --event event.json
```

## Packaging and deployment

AWS Lambda Python runtime requires a flat folder with all dependencies including the application. SAM will use `CodeUri` property to know where to look up for both application and dependencies:

```yaml
...
    DrainerFunction:
        Type: AWS::Serverless::Function
        Properties:
            CodeUri: drainer/
            ...
```

Firstly, we need a `S3 bucket` where we can upload our Lambda functions packaged as ZIP before we deploy anything - If 
you don't have a S3 bucket to store code artifacts then this is a good time to create one:

*Note: The S3 bucket needs to be in the AWS region used to deploy the Lambda.*

```bash
aws s3 mb s3://${BUCKET_NAME}
```


Run the following command to package our Lambda function to S3:

```bash
sam package \
    --output-template-file packaged.yaml \
    --s3-bucket ${BUCKET_NAME}
```

Next, the following command will create a Cloudformation Stack and deploy your SAM resources.

```bash
sam deploy \
    --template-file packaged.yaml \
    --stack-name k8s-drainer \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides AutoScalingGroup=${YOUR_AUTOSCALING_GROUP_NAME} EksCluster=${YOUR_CLUSTER_NAME}
```

> **See [Serverless Application Model (SAM) HOWTO Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-quick-start.html) for more details in how to get started.**

There is a convenience script in the root directory called `build_deploy.sh` that
wraps these three commands and takes your AWS profile as an argument (it will use the default profile
if a profile is not provided) and the S3 bucket created above.
```bash
./build_deploy.sh 
    ${BUCKET_NAME} \
    ${YOUR_AUTOSCALING_GROUP_NAME} \
    ${YOUR_CLUSTER_NAME} \
    ${YOUR_AWS_PROFILE}
```

After deployment is complete you can run the following command to retrieve the API Gateway Endpoint URL:

```bash
aws cloudformation describe-stacks \
    --stack-name k8s-drainer \
    --output table
``` 

## Kubernetes Permissions

After deployment there will be an IAM role associated with the lambda that needs to be mapped to a user or group in 
the EKS cluster. To create the Kubernetes `ClusterRole` and `ClusterRoleBinding` run the following shell command from the root 
directory of the project:

```bash
kubectl apply -R -f k8s_rbac/
```

You may now create the mapping to the IAM role created when deploying the Drainer function. 
You can find this role by checking the `DrainerRole` output of the CloudFormation stack created by the `sam deploy`
command above. Run `kubectl edit -n kube-system configmap/aws-auth` and add the following `yaml`:

```yaml
mapRoles: | 
# ...
    - rolearn: <DrainerFunction IAM role>
      username: lambda
```

## Testing the Drainer function

Run the following command to simulate an EC2 instance being terminated as part of a scale-in event:

```bash
aws autoscaling terminate-instance-in-auto-scaling-group --no-should-decrement-desired-capacity --instance-id <instance-id>
```

You must use this command for Auto Scaling Lifecycle hooks to be used. Terminating the instance via the EC2 Console or APIs will immediately terminate the instance, bypassing the lifecycle hooks.

## Fetch, tail, and filter Lambda function logs

To simplify troubleshooting, SAM CLI provides a command called `sam logs`. `sam logs` lets you fetch logs generated by your Lambda function from the command line. In addition to printing the logs on the terminal, this command has several  features to help you quickly find the bug.

`NOTE`: This command works for all AWS Lambda functions; not just the ones you deploy using SAM.

```bash
sam logs -n DrainerFunction --stack-name k8s-drainer --tail
```

You can find more information and examples about filtering Lambda function logs in the [SAM CLI Documentation](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-logging.html).

## Unit Tests

To run the unit tests, install the test dependencies and run `pytest` against the `tests` directory:

```bash
pipenv install --dev --ignore-pipfile
pipenv run py.test --cov=drainer
```

## Cleanup

In order to remove the EKS Node Drainer Lambda function and Lifecycle Hook you can use the following AWS CLI Command:

```bash
aws cloudformation delete-stack --stack-name k8s-drainer
```

To remove the Kubernetes `ClusterRole` and `ClusterRoleBinding`, run the following commands:

```bash
kubectl delete clusterrolebinding lambda-user-cluster-role-binding

kubectl delete clusterrole lambda-cluster-access
```

## License Summary

This sample code is made available under a modified MIT license. See the LICENSE file.

# Appendix

## Building the project

[AWS Lambda requires a flat folder](https://docs.aws.amazon.com/lambda/latest/dg/lambda-python-how-to-create-deployment-package.html) with the application as well as its dependencies in the deployment package. When you make changes to the source code or dependency manifest,
run the following command to build your project local testing and deployment:

```bash
sam build
```

If your dependencies contain native modules that need to be compiled specifically for the operating system running on AWS Lambda, use this command to build inside a Lambda-like Docker container instead:
```bash
sam build --use-container
```

By default, built artifacts are written to the `.aws-sam/build` directory.

## Limitations

This solution works on a per cluster per autoscaling group basis, multiple autoscaling groups will require a separate 
deployment for each group.

Certain types of pod cannot be evicted from a node, so this lambda will not attempt to evict DaemonSets or mirror pods.
