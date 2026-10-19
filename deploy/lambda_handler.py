"""AWS Lambda entry point (container image, arm64 / Graviton) behind an API Gateway HTTP API (payload v2).

Environment: TABLE (DynamoDB), BUCKET (S3 uploads, private, 1-day expiry), MODEL_ID (Bedrock Converse model,
default us.amazon.nova-2-lite-v1:0), CW_VISIT_SECRET (salt of the anonymous visitor hash), CW_MAX_* (cost caps).
No credentials in the image: the function role grants S3/DynamoDB on its own resources and bedrock:InvokeModel
on one model only.
"""
import base64
import json
import os

import boto3
from botocore.config import Config

from crackwatch.agent import NovaConversePlanner
from crackwatch.api import App, S3Blobs
from crackwatch.store import DynamoStore

_bedrock = boto3.client("bedrock-runtime", config=Config(read_timeout=12, connect_timeout=3, retries={"max_attempts": 1}))
MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-2-lite-v1:0")


def _planner(allow_call):
    return NovaConversePlanner(client=_bedrock, model=MODEL_ID, allow_call=allow_call)


app = App(DynamoStore(os.environ["TABLE"]), S3Blobs(os.environ["BUCKET"]), _planner)


def handler(event, context):
    rc = event.get("requestContext", {}).get("http", {})
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    headers = dict(event.get("headers") or {})
    if event.get("cookies"):
        headers["cookie"] = "; ".join(event["cookies"])
    r = app.handle(rc.get("method", "GET"), event.get("rawPath", "/"), headers, raw,
                   event.get("queryStringParameters") or {}, rc.get("sourceIp", ""))
    out_headers = {k: v for k, v in r.headers.items() if k != "set-cookie"}
    resp = {"statusCode": r.status, "headers": out_headers}
    if "set-cookie" in r.headers:
        resp["cookies"] = [r.headers["set-cookie"]]
    ctype = r.headers.get("content-type", "")
    if ctype.startswith(("text/", "application/json", "image/svg")):
        resp["body"] = r.body.decode()
        resp["isBase64Encoded"] = False
    else:
        resp["body"] = base64.b64encode(r.body).decode()
        resp["isBase64Encoded"] = True
    return resp


if __name__ == "__main__":   # smoke test inside the image: python lambda_handler.py
    print(json.dumps(handler({"rawPath": "/api/health", "requestContext": {"http": {"method": "GET"}}}, None))[:300])
