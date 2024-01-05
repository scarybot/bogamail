import time
import yaml
from lib.email import Email, wait_for_email
from lib.llm_wrapper import LLMInterface

# load the config
with open('./src/config.yaml', 'r') as file:
    config = yaml.safe_load(file)

llm = LLMInterface(root_prompt=config['system']['prompt'])


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

    subject = "RE: " + received_email.subject

    # need to feed the history in...
    try:
        personality = config['accounts'][received_email.recipient.email]['personality']
    except KeyError:
        personality = ""
    print(f"Responding to: \n {received_email.body}")
    print(f"Responding as: \"{received_email.recipient.email}\" \n {personality}")

    llm.start_new_chat(user_prompt=personality)
    response = llm.respond_to(received_email.body)

    print("=" * 32)
    print(subject)
    print(response)

    '''
    return received_email.reply(
        subject="Hello yourself",
        body="Well hello there!!",
    )
    '''


main()
