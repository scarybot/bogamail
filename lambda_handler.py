import json
import os
import base64
import boto3
import smtplib
from datetime import datetime
from lib.email import Email


def is_base64(s):
    try:
        return base64.b64encode(base64.b64decode(s)).decode() == s
    except Exception:
        return False


def get_emails_to_be_sent() -> list[Email]:
    dynamodb_client = boto3.client("dynamodb")
    current_timestamp = int(datetime.now().timestamp())

    response = dynamodb_client.query(
        TableName=os.environ["MAIL_TABLE"],
        IndexName="SendIndex",
        KeyConditionExpression="send_after >= :send_after AND sent = :sent",
        ExpressionAttributeValues={
            ":sent": {"BOOL": False},
            ":send_after": {"N": current_timestamp},
        },
    )

    return [
        Email.from_message_string(item.get("message")["S"])
        for item in response["Items"]
    ]


def send_email(email: Email) -> bool:
    ssm = boto3.client("ssm")
    parameter = ssm.get_parameter(
        Name=f"/bogamail/passwords/{email.sender.email.split('@')[0]}",
        WithDecryption=True,
    )
    password = parameter["Parameter"]["Value"]

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(email.sender.email, password)
            server.send_message(email.message.as_string())
            print(f"Email sent successfully to {email.recipient.email}")
            return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def get_most_recent_message_id(from_email: str) -> str:
    dynamodb_client = boto3.client("dynamodb")
    response = dynamodb_client.query(
        TableName=os.environ["MAIL_TABLE"],
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

        decoded_message = (
            base64.b64decode(sns_message["Message"]["content"])
            if is_base64(sns_message["Message"]["content"])
            else sns_message["Message"]["content"]
        ).decode("utf-8")

        email = Email.from_message_string(decoded_message, "in")
        email.write()

        print(f"Received message: {email.message_id}")
        email.enqueue_for_client()

    return {"statusCode": 200, "body": json.dumps("Messages processed successfully")}


def send_handler(event, context):
    for record in event["Records"]:
        decoded_email = base64.b64decode(json.loads(record["body"])).decode("utf-8")
        this_email = Email.from_message_string(decoded_email, "out")

        if this_email.send_after is None:
            send_email(this_email)
            this_email.sent = True

        this_email.write()

    return {"statusCode": 200, "body": json.dumps("Messages processed successfully")}


def schedule_handler(event, context):
    session = boto3.session.Session()

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
