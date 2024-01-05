import time
from lib.email import Email, wait_for_email
from lib.data import store_scam_data, get_scam_data

def main():
    while True:
        emails = wait_for_email()
        for this_email in emails:
            generate_reply_to(this_email).enqueue_for_send()

        # rate limiter
        time.sleep(1)


def generate_reply_to(received_email: Email) -> Email:
    for previous in received_email.thread():
        # Just to give you an idea, this prints the previous emails in the thread. It might be tricky to isolate the most
        # recent response, as each reply seems to usually include all previous responses, quoted with > marks.
        print(f"{previous.sender.name}: {previous.body}")

    return received_email.reply(
        subject="Hello yourself",
        body="Well hello there!!",
    )


main()
