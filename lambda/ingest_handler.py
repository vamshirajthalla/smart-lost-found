"""
ingest_handler.py
------------------
Triggered directly by an AWS IoT Core topic rule subscribed to
lostfound/+/scan. Each scan toggles the item's status in DynamoDB
(the cloud is the single source of truth, not the device) and publishes
the result back to lostfound/<boxId>/status so the box's OLED can show
what just happened.

DynamoDB item shape:
{
  "itemId": "04A3B2C1",           # RFID tag UID, partition key
  "status": "CHECKED_IN" | "CHECKED_OUT",
  "itemName": "Blue Hydro Flask", # editable later via the admin API
  "description": "",
  "boxId": "box-01",
  "firstSeen": "2026-09-01T12:00:00Z",
  "lastSeen": "2026-09-10T08:15:00Z",
  "scanCount": 3,
  "history": [ {"action": "CHECKED_IN", "ts": "...", "boxId": "..."}, ... ]
}
"""

import os
import json
import time
import datetime
import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]
IOT_ENDPOINT = os.environ["IOT_DATA_ENDPOINT"]  # e.g. xxxx-ats.iot.us-east-1.amazonaws.com

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
iot_data = boto3.client("iot-data", endpoint_url=f"https://{IOT_ENDPOINT}")

MAX_HISTORY = 25


def _now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def handler(event, context):
    """
    `event` is the raw MQTT payload published by the device:
      {"itemId": "04A3B2C1", "boxId": "box-01", "ts": 12345}
    (The IoT rule invokes Lambda with the message body as the event.)
    """
    tag_id = event.get("itemId")
    box_id = event.get("boxId", "unknown-box")

    if not tag_id:
        return {"statusCode": 400, "body": "missing itemId"}

    now = _now_iso()

    existing = table.get_item(Key={"itemId": tag_id}).get("Item")

    if existing is None:
        # First time this tag has ever been seen: treat as a check-in
        # of a newly found item.
        new_status = "CHECKED_IN"
        item = {
            "itemId": tag_id,
            "status": new_status,
            "itemName": "Unidentified item",
            "description": "",
            "boxId": box_id,
            "firstSeen": now,
            "lastSeen": now,
            "scanCount": 1,
            "history": [{"action": new_status, "ts": now, "boxId": box_id}],
        }
        table.put_item(Item=item)
    else:
        # Toggle status
        new_status = "CHECKED_OUT" if existing.get("status") == "CHECKED_IN" else "CHECKED_IN"
        history = existing.get("history", [])
        history.append({"action": new_status, "ts": now, "boxId": box_id})
        history = history[-MAX_HISTORY:]

        try:
            table.update_item(
                Key={"itemId": tag_id},
                UpdateExpression=(
                    "SET #s = :status, lastSeen = :now, boxId = :box, "
                    "scanCount = if_not_exists(scanCount, :zero) + :one, "
                    "history = :history"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": new_status,
                    ":now": now,
                    ":box": box_id,
                    ":zero": 0,
                    ":one": 1,
                    ":history": history,
                },
            )
            item = {**existing, "status": new_status, "lastSeen": now}
        except ClientError as e:
            print(f"DynamoDB update failed: {e}")
            return {"statusCode": 500, "body": "update failed"}

    # Tell the box what happened so the OLED can display it
    status_topic = f"lostfound/{box_id}/status"
    payload = {
        "itemId": tag_id,
        "itemName": item.get("itemName", "Unidentified item"),
        "action": new_status.lower(),  # "checked_in" / "checked_out"
        "ts": now,
    }
    try:
        iot_data.publish(topic=status_topic, qos=0, payload=json.dumps(payload))
    except ClientError as e:
        # Non-fatal: the DynamoDB write already succeeded.
        print(f"Failed to publish status to {status_topic}: {e}")

    return {"statusCode": 200, "body": json.dumps(payload)}
