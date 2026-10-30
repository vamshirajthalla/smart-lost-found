"""
CloudFormation custom resource: looks up this account's IoT Core data-plane
endpoint (ATS type) so it can be wired into the ingest Lambda's environment
without the user having to hardcode it in the template.
"""
import boto3
import urllib.request
import json

iot = boto3.client("iot")


def send_response(event, context, status, data):
    body = json.dumps({
        "Status": status,
        "Reason": f"See CloudWatch Logs: {context.log_stream_name}",
        "PhysicalResourceId": context.log_stream_name,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data,
    }).encode("utf-8")

    req = urllib.request.Request(
        url=event["ResponseURL"],
        data=body,
        method="PUT",
        headers={"Content-Type": "", "Content-Length": str(len(body))},
    )
    urllib.request.urlopen(req)


def handler(event, context):
    try:
        if event["RequestType"] in ("Create", "Update"):
            resp = iot.describe_endpoint(endpointType="iot:Data-ATS")
            data = {"Endpoint": resp["endpointAddress"]}
        else:
            data = {"Endpoint": ""}
        send_response(event, context, "SUCCESS", data)
    except Exception as e:
        print(f"Error: {e}")
        send_response(event, context, "FAILED", {"Error": str(e)})
