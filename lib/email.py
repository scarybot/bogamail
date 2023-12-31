import boto3
import email
from dataclasses import dataclass, field
import re
import os
import uuid

queue_url_cache = {}


def queue_url(name: str) -> str:
    global queue_url_cache
    if queue_url_cache[name] is not None:
        return queue_url_cache[name]

    ssm = boto3.client("ssm")
    parameter = ssm.get_parameter(Name=f"/bogamail/queue_url/{name}")
    queue_url_cache[name] = parameter["Parameter"]["Value"]
    return queue_url_cache[name]


def extract_id(id_header):
    match = re.search(r"^<(.+)>", id_header)
    if match:
        return match.group(1).strip()
    return None


def generate_message_id(domain="gmail.com"):
    return "<" + str(uuid.uuid4()) + f"@{domain}>"


@dataclass
class Contact:
    name: str
    email: str

    def __init__(self, name, email):
        self.name = name
        self.email = email

    @classmethod
    def from_header(self, header):
        match = re.search(r"^\"?(.*?)\"?\s*<\"?(.+@.+\..+?)>\"?", header)
        print(match)
        if match:
            return self(match.group(1).strip(), match.group(2).strip())

    def to_header(self):
        return f"{self.name} <{self.email}>"


@dataclass
class Email:
    sender: Contact
    recipient: Contact
    subject: str
    body: str
    references: list[str] = (field(default_factory=list),)
    _message_id: str = None
    sent: bool = False

    @classmethod
    def from_message_string(self, email_string, direction):
        parsed_email = email.message_from_string(email_string)
        sender = Contact.from_header(parsed_email["From"])
        recipient = Contact.from_header(parsed_email["To"])

        references = (
            parsed_email["References"].split(",") if parsed_email["References"] else []
        )

        if parsed_email.get("Message-ID"):
            message_id = extract_id(parsed_email.get("Message-ID"))
        else:
            message_id = generate_message_id(self.sender.email.split("@")[1])

        return self(
            from_address=sender,
            to_address=recipient,
            subject=parsed_email["Subject"],
            body=parsed_email.get_payload(),
            references=references,
            message_id=message_id,
            message=parsed_email,
            direction=direction,
        )

    @classmethod
    def from_id(self, id: str):
        dynamodb = boto3.client("dynamodb")
        response = dynamodb.get_item(
            TableName=os.environ["MAIL_TABLE"],
            Key={"id": {"S": id}},
        )

        if "Item" in response:
            return Email.from_message_string(response["Item"].get("body"))
        else:
            return None

    def message_id(self):
        if self._message_id:
            return self._message_id
        else:
            self._message_id = generate_message_id(self.sender.email.split("@")[1])

        return self._message_id

    def as_message(self):
        msg = email.Message.message()
        msg["From"] = self.sender.to_header()
        msg["To"] = self.recipient.to_header()
        msg["Subject"] = self.subject
        msg["References"] = ",".join(self.references)
        msg.set_payload(self.body)
        return msg

    def enqueue_for_client(self):
        sqs = boto3.client("sqs")
        return sqs.send_message(
            QueueUrl=queue_url("client"),
            MessageBody=ClientReceiveMessage(email=self.as_message().as_string()),
        )

    def reply(self, subject, body):
        return Email(
            sender=self.recipient,
            recipient=self.sender,
            subject=subject,
            body=body,
            references=self.references + [self.message_id()],
        )

    def thread(self):
        return [Email.from_id(id) for id in self.references]

    def as_dynamodb_item(self):
        parsed_email = self.as_message()

        item = {
            "direction": {"S": self.direction},
            "sender": {"S": self.sender.email},
            "sender_name": {"S": self.sender.name},
            "recipient": {"S": self.recipient.email},
            "recipient_name": {"S": self.recipient.name},
            "id": {"S": self.message_id()},
            "subject": {"S": self.subject},
            "message": {"S": parsed_email.as_string()},
            "sent": {"S": self.sent},
        }

        return item

    def write(self):
        dynamodb_client = boto3.client("dynamodb")
        response = dynamodb_client.put_item(
            TableName=os.environ["MAIL_TABLE"],
            Item=self.as_dynamodb_item(self.direction),
        )
        return response

    def enqueue_for_send(self, after_ts=0):
        sqs = boto3.client("sqs")
        return sqs.send_message(
            QueueUrl=queue_url("send"),
            MessageBody=ClientReplyMessage(
                email=self.as_message().as_string(), send_after=after_ts
            ),
        )


@dataclass
class IncomingMailMessage:
    email: Email


@dataclass
class ClientReceiveMessage:
    email: Email


@dataclass
class ClientReplyMessage:
    email: Email
    send_after: int = 0


def wait_for_email() -> list[Email]:
    sqs = boto3.client("sqs")
    while True:
        response = sqs.receive_message(
            QueueUrl=queue_url("client"),
            MaxNumberOfMessages=20,
            WaitTimeSeconds=20,
        )

        messages = response.get("Messages", [])
        for message in messages:
            receipt_handle = message["ReceiptHandle"]
            sqs.delete_message(
                QueueUrl=queue_url("client"), ReceiptHandle=receipt_handle
            )

        return (
            [Email.from_message_string(message["message"]) for message in messages]
            if len(messages) > 1
            else None
        )
