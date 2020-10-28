#!/usr/bin/env bash
set -o nounset
set -o errexit
BUCKET=$1
ASG=$2
CLUSTER=$3
PROFILE=${4:-default}

sam build --use-container --skip-pull-image --profile ${PROFILE}
sam package --s3-bucket ${BUCKET} --output-template-file packaged.yaml --profile ${PROFILE}
sam deploy --template-file packaged.yaml --stack-name k8s-drainer-${CLUSTER} --capabilities CAPABILITY_IAM --profile ${PROFILE} --parameter-overrides AutoScalingGroup=${ASG} EksCluster=${CLUSTER}
