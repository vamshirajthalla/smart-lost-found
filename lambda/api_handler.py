"""
api_handler.py
---------------
Backs the HTTP API (API Gateway) that the S3 frontend calls.

Routes (HTTP API with Lambda proxy integration, routeKey-based):
  GET    /items               -> list items (optional ?status=CHECKED_IN)
  GET    /items/{itemId}      -> single item detail
  PUT    /items/{itemId}      -> update editable metadata (itemName, description, ownerContact)
  POST   /items/{itemId}/claim -> staff marks an item claimed / checked out by hand
"""

import os
import json
import datetime
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
STATUS_INDEX = os.environ.get("STATUS_INDEX_NAME", "StatusIndex")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,PUT,POST,OPTIONS",
}

EDITABLE_FIELDS = {"itemName", "description", "ownerContact"}


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def list_items(query_params):
    status = (query_params or {}).get("status")
    if status:
        resp = table.query(
            IndexName=STATUS_INDEX,
            KeyConditionExpression=Key("status").eq(status.upper()),
            ScanIndexForward=False,  # most recently seen first
        )
    else:
        resp = table.scan()
    return resp.get("Items", [])


def get_item(item_id):
    return table.get_item(Key={"itemId": item_id}).get("Item")


def update_item(item_id, body):
    updates = {k: v for k, v in body.items() if k in EDITABLE_FIELDS}
    if not updates:
        return None, "no editable fields provided"

    expr_names = {f"#{k}": k for k in updates}
    expr_values = {f":{k}": v for k, v in updates.items()}
    update_expr = "SET " + ", ".join(f"#{k} = :{k}" for k in updates)

    try:
        table.update_item(
            Key={"itemId": item_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
            ConditionExpression="attribute_exists(itemId)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None, "item not found"
        raise
    return get_item(item_id), None


def claim_item(item_id, body):
    now = _now_iso()
    owner = (body or {}).get("ownerContact", "")
    try:
        table.update_item(
            Key={"itemId": item_id},
            UpdateExpression=(
                "SET #s = :status, lastSeen = :now, ownerContact = :owner"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "CHECKED_OUT",
                ":now": now,
                ":owner": owner,
            },
            ConditionExpression="attribute_exists(itemId)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None, "item not found"
        raise
    return get_item(item_id), None


def handler(event, context):
    route_key = event.get("routeKey", "")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    if method == "OPTIONS":
        return _response(200, {})

    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}
    item_id = path_params.get("itemId")

    try:
        body = json.loads(event["body"]) if event.get("body") else {}
    except json.JSONDecodeError:
        return _response(400, {"error": "invalid JSON body"})

    try:
        if route_key == "GET /items":
            return _response(200, {"items": list_items(query_params)})

        if route_key == "GET /items/{itemId}":
            item = get_item(item_id)
            if not item:
                return _response(404, {"error": "item not found"})
            return _response(200, item)

        if route_key == "PUT /items/{itemId}":
            item, err = update_item(item_id, body)
            if err:
                return _response(404 if err == "item not found" else 400, {"error": err})
            return _response(200, item)

        if route_key == "POST /items/{itemId}/claim":
            item, err = claim_item(item_id, body)
            if err:
                return _response(404, {"error": err})
            return _response(200, item)

        return _response(404, {"error": f"no handler for {route_key}"})

    except ClientError as e:
        print(f"DynamoDB error: {e}")
        return _response(500, {"error": "internal server error"})
