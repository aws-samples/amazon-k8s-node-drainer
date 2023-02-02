#!/usr/bin/env bash
set -o nounset
set -o errexit

BUCKET=$1
ASG=$2
NAME=$3
PROFILE=${4:-default}

sam build --profile ${PROFILE} \
&& sam package --profile ${PROFILE} \
    --output-template-file packaged.yaml \
    --s3-bucket ${BUCKET} \
&& sam deploy --profile ${PROFILE} \
    --stack-name asg-deregister-${NAME} \
    --template-file packaged.yaml \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides AutoScalingGroup=${ASG} \
    --s3-bucket ${BUCKET}

exit 0