[![Build Status](https://travis-ci.org/aws-samples/amazon-k8s-node-drainer.svg?branch=master)](https://travis-ci.org/aws-samples/amazon-k8s-node-drainer)

> *Note* This repository is archived and this code is not maintained anymore. We recommend using the [Karpenter](https://karpenter.sh/) tool for the functionality this repo provided.

# Amazon EKS Node Drainer [DEPRECATED]

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

This lambda can also be used against a non-EKS Kubernetes cluster by reading a `kubeconfig` file from an S3 bucket
specified by the `KUBE_CONFIG_BUCKET` and `KUBE_CONFIG_OBJECT` environment variables. If these two variables are passed 
in then Drainer function will assume this is a non-EKS cluster and the IAM authenticator signatures will _not_ be added 
to Kubernetes API requests. It is recommended to apply the principle of least privilege to the IAM role that governs
access between the Lambda function and S3 bucket.
