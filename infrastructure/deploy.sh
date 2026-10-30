#!/usr/bin/env bash
# Deploys the Campus Lost & Found stack and provisions one physical box
# (IoT Thing + certificate + policy). Run again with a different BOX_ID
# for additional boxes.
#
# Requires: AWS CLI v2 configured, SAM CLI installed.
set -euo pipefail

STACK_NAME="${STACK_NAME:-campus-lost-found}"
BOX_ID="${BOX_ID:-box-01}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region)}}"
REGION="${REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
OUT_DIR="./certs/${BOX_ID}"

echo "==> 1. Building and deploying the SAM stack (${STACK_NAME})"
sam build --template-file template.yaml
sam deploy \
  --stack-name "${STACK_NAME}" \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset

echo "==> 2. Provisioning IoT Thing for ${BOX_ID}"
mkdir -p "${OUT_DIR}"

aws iot create-thing --thing-name "smartbox-${BOX_ID}" >/dev/null

CERT_JSON=$(aws iot create-keys-and-certificate --set-as-active \
  --certificate-pem-outfile "${OUT_DIR}/certificate.pem.crt" \
  --public-key-outfile "${OUT_DIR}/public.pem.key" \
  --private-key-outfile "${OUT_DIR}/private.pem.key")

CERT_ARN=$(echo "${CERT_JSON}" | python3 -c "import sys, json; print(json.load(sys.stdin)['certificateArn'])")

echo "==> 3. Creating and attaching a scoped IoT policy"
sed "s/REGION/${REGION}/g; s/ACCOUNT_ID/${ACCOUNT_ID}/g" iot-policy.json > "${OUT_DIR}/iot-policy.rendered.json"

aws iot create-policy \
  --policy-name "LostFoundBoxPolicy-${BOX_ID}" \
  --policy-document "file://${OUT_DIR}/iot-policy.rendered.json" >/dev/null || true

aws iot attach-policy --policy-name "LostFoundBoxPolicy-${BOX_ID}" --target "${CERT_ARN}"
aws iot attach-thing-principal --thing-name "smartbox-${BOX_ID}" --principal "${CERT_ARN}"

echo "==> 4. Downloading Amazon Root CA1"
curl -sS -o "${OUT_DIR}/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem

echo "==> 5. Looking up IoT data endpoint"
ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)

echo ""
echo "Done. Files for this box are in ${OUT_DIR}/"
echo ""
echo "Next steps:"
echo "  1. Copy firmware/secrets_template.h to firmware/secrets.h"
echo "  2. Set AWS_IOT_ENDPOINT to: ${ENDPOINT}"
echo "  3. Paste the contents of:"
echo "       ${OUT_DIR}/AmazonRootCA1.pem   -> AWS_ROOT_CA1"
echo "       ${OUT_DIR}/certificate.pem.crt -> AWS_CERT_CRT"
echo "       ${OUT_DIR}/private.pem.key     -> AWS_CERT_PRIVATE"
echo "  4. Flash the ESP32 with firmware/smart_box_esp32.ino"
echo ""
aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs" --output table
