#!/usr/bin/env bash
# One-command deployment of the CrackWatch demo (us-east-1). Uses YOUR AWS credentials (never stored here).
#   AWS_PROFILE=<profile> deploy/deploy.sh
# Steps: ECR repository (keeps the 3 newest images) -> arm64 image built without Docker -> CloudFormation stack.
# The anonymous-visit salt is generated once and kept OUTSIDE the repository (default ~/.config/crackwatch/).
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-us-east-1}"
STACK="${CW_STACK:-crackwatch}"
REPO_NAME="${CW_REPO:-crackwatch}"
SECRET_FILE="${CW_SECRET_FILE:-$HOME/.config/crackwatch/visit-secret}"
PY="${PYTHON:-python3}"
TAG="$(date -u +%Y%m%d-%H%M%S)"

ACC="$(aws sts get-caller-identity --query Account --output text)"
REG="$ACC.dkr.ecr.$REGION.amazonaws.com"

if ! aws ecr describe-repositories --region "$REGION" --repository-names "$REPO_NAME" >/dev/null 2>&1; then
  aws ecr create-repository --region "$REGION" --repository-name "$REPO_NAME" \
    --image-scanning-configuration scanOnPush=false --tags Key=project,Value=crackwatch >/dev/null
  aws ecr put-lifecycle-policy --region "$REGION" --repository-name "$REPO_NAME" --lifecycle-policy-text \
    '{"rules":[{"rulePriority":1,"description":"keep the 3 newest images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":3},"action":{"type":"expire"}}]}' >/dev/null
fi
aws ecr get-login-password --region "$REGION" | crane auth login "$REG" -u AWS --password-stdin >/dev/null

IMAGE="$("$PY" deploy/build_image.py --repo "$REG/$REPO_NAME" --tag "$TAG" | tail -1)"
echo "image: $IMAGE"

mkdir -p "$(dirname "$SECRET_FILE")"
[ -s "$SECRET_FILE" ] || (umask 077; "$PY" -c "import secrets; print(secrets.token_hex(24))" > "$SECRET_FILE")

aws cloudformation deploy --region "$REGION" --stack-name "$STACK" --template-file deploy/template.yaml \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --no-fail-on-empty-changeset \
  --tags project=crackwatch \
  --parameter-overrides "ImageUri=$IMAGE" "VisitSecret=$(cat "$SECRET_FILE")"

aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
  --query 'Stacks[0].Outputs[?OutputKey==`DemoUrl`].OutputValue' --output text
