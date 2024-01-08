import time
import yaml
from lib.email import Email, wait_for_email
from lib.llm_wrapper import LLMInterface

# load the config
with open('./src/config.yaml', 'r') as file:
    config = yaml.safe_load(file)

llm = LLMInterface(root_prompt=config['system']['prompt'])

def clean_email(message:str) -> str:
    '''
    Remove all the threads ">" from a string
    :param message: string
    :return: string
    '''
    email = ""
    for line in message.splitlines():
        if not line.strip().startswith(">"):
            email += line.strip()

    return email


def main():
    while True:
        emails = wait_for_email()
        for this_email in emails:
            generate_reply_to(this_email).enqueue_for_send()

        # rate limiter
        time.sleep(1)


def generate_reply_to(received_email: Email) -> Email:
    email_thread = ""
    for previous in received_email.thread():
        email_thread += f"{previous.sender.name}: \n{previous.body}"

    llm.parse_history(email_thread)

    subject = "RE: " + received_email.subject

    # need to feed the history in...
    try:
        personality = config['accounts'][received_email.recipient.email]['personality']
    except KeyError:
        personality = ""

    print(clean_email(received_email.body))

    llm.start_new_chat(user_prompt=personality)
    response = llm.respond_to(clean_email(received_email.body))

    print("=" * 32)
    print(response)

    return received_email.reply(
        subject=subject,
        body=response,
    )



main()
