import json
import os
import base64
import boto3
import smtplib
import time
from datetime import datetime
from lib.email import Email, mail_table


def is_base64(s):
    try:
        return base64.b64encode(base64.b64decode(s)).decode() == s
    except Exception:
        return False


def get_emails_to_be_sent() -> list[Email]:
    dynamodb_client = boto3.client("dynamodb")
    current_timestamp = int(time.time())

    response = dynamodb_client.query(
        TableName=mail_table(),
        IndexName="SendIndex",
        KeyConditionExpression="send_after >= :send_after AND sent = :sent",
        ExpressionAttributeValues={
            ":sent": {"S": str(False)},
            ":send_after": {"N": str(current_timestamp)},
        },
    )

    return [
        Email.from_message_string(item.get("message")["S"])
        for item in response["Items"]
    ]


def send_email(email: Email) -> bool:
    ssm = boto3.client("ssm")
    dynamodb = boto3.client("dynamodb")

    pw_parameter = ssm.get_parameter(
        Name=f"/bogamail/passwords/{email.sender.email.split('@')[0]}",
        WithDecryption=True,
    )
    password = pw_parameter["Parameter"]["Value"]

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(email.sender.email, password)
            server.send_message(email.message)
            print(f"Email sent successfully to {email.recipient.email}")

        dynamodb.update_item(
            TableName=mail_table(),
            Key={"id": {"S": email.get_message_id()}, "sender": {"S": email.sender.email}},
            UpdateExpression="SET sent = :sent",
            ExpressionAttributeValues={":sent": {"S": "true"}},
        )

        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def get_most_recent_message_id(from_email: str) -> str:
    dynamodb_client = boto3.client("dynamodb")
    response = dynamodb_client.query(
        TableName=mail_table(),
        KeyConditionExpression="from = :from",
        ExpressionAttributeValues={":from": {"S": from_email}},
        ScanIndexForward=False,
        Limit=1,
    )
    if response["Count"] > 0:
        return response["Items"][0]["id"]["S"]
    return None


def receive_handler(event, context):
    for record in event["Records"]:
        sns_message = json.loads(record["body"])
        ses_message = json.loads(sns_message["Message"])
        print(sns_message)

        decoded_message = (
            base64.b64decode(ses_message["content"])
            if is_base64(ses_message["content"])
            else ses_message["content"]
        ).decode("utf-8")

        email = Email.from_message_string(decoded_message)
        email.write()

        print(f"Received message: {email.get_message_id()}")
        email.enqueue_for_client()
        print(f"Enqueued message: {email.get_message_id()}")

    return {"statusCode": 200, "body": json.dumps("Messages processed successfully")}


def send_handler(event, context):
    for record in event["Records"]:
        decoded_email = json.loads(record["body"])
        print(decoded_email)
        this_email = Email.from_message_string(decoded_email.get("email"))

        if decoded_email.get("send_after", 0) == 0:
            try:
                send_email(this_email)
                this_email.sent = True
                this_email.write()
            except:
                return {"statusCode": 500, "body": json.dumps("Error sending email")}

    return {"statusCode": 200, "body": json.dumps("Messages processed successfully")}


def schedule_handler(event, context):
    for this_email in get_emails_to_be_sent():
        send_email(this_email)

        return {
            "statusCode": 200,
            "body": json.dumps("Messages processed successfully"),
        }


if __name__ == "__main__":
    with open("test_event.json") as f:
        event_body = f.read()

        event = {
            "Records": [
                {
                    "messageId": "example-message-id",
                    "receiptHandle": "example-receipt-handle",
                    "body": json.dumps({"Message": json.loads(event_body)}),
                    "attributes": {
                        "ApproximateReceiveCount": "1",
                        "SentTimestamp": "1644457395000",
                        "SenderId": "example-sender-id",
                        "ApproximateFirstReceiveTimestamp": "1644457396000",
                    },
                    "messageAttributes": {},
                    "md5OfBody": "example-md5-of-body",
                    "eventSource": "aws:sqs",
                    "eventSourceARN": "arn:aws:sqs:example-region:123456789012:example-queue",
                    "awsRegion": "example-region",
                }
            ]
        }

        send_handler(event, None)
