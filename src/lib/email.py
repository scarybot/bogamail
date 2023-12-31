import boto3
import email
from dataclasses import dataclass, field
import re
import os
import uuid
from typing import Self
import json
import logging
import string

queue_url_cache = {}
mail_table_cache = None
logging.basicConfig(level=logging.INFO)


def queue_url(name: str) -> str:
    global queue_url_cache
    if queue_url_cache.get(name) is not None:
        return queue_url_cache[name]

    if os.environ.get(f"{name.upper()}_QUEUE_URL"):
        return os.environ.get(f"{name.upper()}_QUEUE_URL")
    else:
        ssm = boto3.client("ssm")
        parameter = ssm.get_parameter(Name=f"/bogamail/queue_url/{name.lower()}")
        queue_url_cache[name] = parameter["Parameter"]["Value"]
        return queue_url_cache[name]


def mail_table() -> str:
    global mail_table_cache
    if mail_table_cache is not None:
        return mail_table_cache

    if os.environ.get("MAIL_TABLE"):
        return os.environ.get("MAIL_TABLE")
    else:
        ssm = boto3.client("ssm")
        parameter = ssm.get_parameter(Name=f"/bogamail/mail_table")
        mail_table_cache = parameter["Parameter"]["Value"]
        return mail_table_cache


def clean_reference(ref):
    return re.sub(r"[\r\n]+$", "", ref)


def extract_id(id_header):
    match = re.search(r"^<(.+)>", id_header)
    if match:
        return match.group(1).strip()
    return None


def generate_message_id(domain="gmail.com"):
    return "<" + str(uuid.uuid4()) + f"@{domain}>"


def get_plain_text_body(email_message):
    if email_message.is_multipart():
        for part in email_message.walk():
            if part.get_content_type() == "text/plain" and not part.is_multipart():
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8"
                )
    else:
        return email_message.get_payload(decode=True).decode(
            email_message.get_content_charset() or "utf-8"
        )


@dataclass
class Contact:
    name: str
    email: str

    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email

    @classmethod
    def from_header(self, header: str) -> Self:
        match = re.search(
            r"^\"?(.*?)\"?\s*<?([^<>@\s]+@[^<>@\s]+\.[^<>@\s]+)>?$", header
        )

        if match:
            return Contact(match.group(1).strip(), match.group(2).strip())

    def to_header(self) -> str:
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
    message: email.message.EmailMessage = None
    direction: str = "in"
    receipt_handle: str = None

    def __init__(
        self,
        sender: Contact,
        recipient: Contact,
        subject: str,
        body: str,
        references: list[str] = None,
        message_id: str = None,
        message: email.message.EmailMessage = None,
        direction: str = "in",
        receipt_handle: str = None,
    ):
        self.sender = sender
        self.recipient = recipient
        self.subject = subject
        self.body = body
        self.references = references
        self._message_id = message_id
        self.message = message
        self.direction = direction
        self.sent = True if direction == "in" else False
        self.receipt_handle = receipt_handle

    @classmethod
    def from_message_string(
        self, email_string: str, direction: str, receipt_handle: str = None
    ) -> Self:
        parsed_email = email.message_from_string(email_string)
        sender = Contact.from_header(parsed_email["From"])
        recipient = Contact.from_header(parsed_email["To"])

        references = (
            [clean_reference(ref) for ref in parsed_email["References"].split(" ")]
            if parsed_email["References"]
            else []
        )

        cleaned_references = [clean_reference(ref) for ref in references]

        if parsed_email.get("Message-ID"):
            message_id = extract_id(parsed_email.get("Message-ID"))
        else:
            message_id = generate_message_id(sender.email.split("@")[1])

        return self(
            sender=sender,
            recipient=recipient,
            subject=parsed_email["Subject"],
            body=get_plain_text_body(parsed_email),
            references=cleaned_references,
            message_id=message_id,
            message=parsed_email,
            direction=direction,
            receipt_handle=receipt_handle,
        )

    @classmethod
    def from_id(self, id: str) -> Self:
        dynamodb = boto3.client("dynamodb")
        response = dynamodb.get_item(
            TableName=mail_table(),
            Key={"id": {"S": id}},
        )

        if "Item" in response:
            return Email.from_message_string(response["Item"].get("body"))
        else:
            return None

    def get_message_id(self) -> str:
        if self._message_id:
            return self._message_id
        else:
            self._message_id = generate_message_id(self.sender.email.split("@")[1])

        return self._message_id

    def as_message(self):
        msg = email.message.EmailMessage()
        msg["From"] = self.sender.to_header()
        msg["To"] = self.recipient.to_header()
        msg["Subject"] = self.subject

        clean_references = " ".join([clean_reference(ref) for ref in self.references])

        if clean_references:
            msg["References"] = clean_references

        msg.set_content(self.body)
        return msg

    def enqueue_for_client(self):
        sqs = boto3.client("sqs")
        logging.info(
            f"enqueuing email to {self.recipient.email}: subject: {self.subject}, body: {self.body}"
        )
        return sqs.send_message(
            QueueUrl=queue_url("client"),
            MessageBody=ClientReceiveMessage(email=self).as_json(),
        )

    def reply(self, subject, body):
        sqs = boto3.client("sqs")
        ssm = boto3.client("ssm")

        logging.info(
            f"deleting message {self.receipt_handle[:8]}... from receive queue"
        )
        sqs.delete_message(
            QueueUrl=queue_url("client"), ReceiptHandle=self.receipt_handle
        )

        name_parameter = ssm.get_parameter(
            Name=f"/bogamail/names/{self.recipient.email.split('@')[0]}",
            WithDecryption=True,
        )
        name = name_parameter["Parameter"]["Value"]
        sender = Contact(name, self.recipient.email)

        return Email(
            sender=sender,
            recipient=self.sender,
            subject=subject,
            body=body,
            references=[clean_reference(ref) for ref in self.references]
            + [clean_reference(self.get_message_id())],
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
            "id": {"S": self.get_message_id()},
            "subject": {"S": self.subject},
            "message": {"S": parsed_email.as_string()},
            "sent": {"S": str(self.sent)},
        }

        return item

    def write(self):
        dynamodb_client = boto3.client("dynamodb")
        response = dynamodb_client.put_item(
            TableName=mail_table(),
            Item=self.as_dynamodb_item(),
        )
        return response

    def enqueue_for_send(self, after_ts=0):
        sqs = boto3.client("sqs")
        logging.info(
            f"enqueuing reply to {self.recipient.email}: subject: {self.subject}, body: {self.body}"
        )

        return sqs.send_message(
            QueueUrl=queue_url("send"),
            MessageBody=ClientReplyMessage(email=self, send_after=after_ts).as_json(),
        )


@dataclass
class IncomingMailMessage:
    email: Email

    def as_json(self):
        return json.dumps({"email": self.email.as_message().as_string()})


@dataclass
class ClientReceiveMessage:
    email: Email

    def as_json(self):
        return json.dumps({"email": self.email.as_message().as_string()})


@dataclass
class ClientReplyMessage:
    email: Email
    send_after: int = 0

    def as_json(self):
        return json.dumps(
            {
                "email": self.email.as_message().as_string(),
                "send_after": self.send_after,
            }
        )


def wait_for_email() -> list[Email]:
    sqs = boto3.client("sqs")
    logging.info("waiting for email")

    while True:
        response = sqs.receive_message(
            QueueUrl=queue_url("client"),
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
        )

        messages = response.get("Messages", [])
        emails = []

        for message in messages:
            receipt_handle = message["ReceiptHandle"]
            body = json.loads(message["Body"])
            email = Email.from_message_string(body["email"], "in", receipt_handle)
            logging.info(f"email from {email.sender.email} to {email.recipient.email}")

            emails.append(email)

        if len(messages) > 0:
            return emails
