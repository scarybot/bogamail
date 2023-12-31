import time
from lib.email import Email, wait_for_email


def main():
    while True:
        emails = wait_for_email()
        for this_email in emails:
            generate_reply_to(this_email).enqueue_for_send()

        # rate limiter
        time.sleep(1)


def generate_reply_to(received_email: Email) -> Email:
    return received_email.reply(
        subject="Hello yourself",
        body="Well hello there!!",
    )
