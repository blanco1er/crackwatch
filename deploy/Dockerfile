# CrackWatch API Lambda - container image for arm64 (Graviton).
# Equivalent to deploy/build_image.sh, which builds the same image without Docker (crane + pip --platform).
#   docker build --platform linux/arm64 -t crackwatch-api -f deploy/Dockerfile .
FROM public.ecr.aws/lambda/python:3.12-arm64@sha256:9672c8fa29ab0fc33c5b2b22ffe91e99c075d6fc67cc606fcd702a8adee3c5a8

COPY deploy/requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir --only-binary=:all: --target ${LAMBDA_TASK_ROOT} -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt \
    && python -c "import sys; sys.path.insert(0, '${LAMBDA_TASK_ROOT}'); import cv2, numpy; print(cv2.__version__, numpy.__version__)"

COPY crackwatch/ ${LAMBDA_TASK_ROOT}/crackwatch/
COPY web/ ${LAMBDA_TASK_ROOT}/web/
COPY print/card_A6-5x7-15mm.pdf print/card_A5-7x10-17mm.pdf ${LAMBDA_TASK_ROOT}/print/
COPY deploy/lambda_handler.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_handler.handler"]
