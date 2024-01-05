import time
import random
from ctransformers import AutoModelForCausalLM


class LLMInterface:
    def __init__(self, root_prompt: str = None):
        self.llm = AutoModelForCausalLM.from_pretrained("TheBloke/vicuna-7B-v1.3-GPTQ",
                                                        # revision="main",
                                                        revision="gptq-4bit-32g-actorder_True",
                                                        context_length=2048,
                                                        gpu_layers=999)

        self.__max_history = 8

        if root_prompt is not None:
            self.__root_prompt = root_prompt
        else:
            self.__root_prompt = f"An email chain between customer service and an 83 year old man interested in diversifying his wealth with crypto investments. Your name is {name}, you are very curious about their investing platform and want to know all about how it works. The emails you write should be funny. Feign ignorance about how crypto works. Never use foul language, your tone should be in first person and appropriate for all ages. If you are asked to register, make up excuses. If you are asked about a wallet, act clueless and mention buying coins at a nearby ATM."

        self.__examples = [
            "Ask questions like how long the platform has been in business, how safe it is, if any celebrities use it, etc.",
            "Tell a story about a time you learned something interesting about investing."
            "Find out if you will have a personal advisor or manager you can talk to about growing your wealth.",
            "Discuss options of adding more money to the platform over time.",
            "Ask personal questions about the owner or manager of the platform.",
            "Discuss your personal life.",
            "Talk about what you will do if you make a lot of money.",
            "Ask awkward questions somewhat related to money.",
            "Talk about your grandchildren.",
            "Tell a story about your pet."
        ]
        self.__history = []

    def start_new_chat(self, user_prompt: str = ""):
        # restart the session / clear the history
        self.llm.reset()  # I assume this will work ??
        self.add_history("system", self.__root_prompt)
        if user_prompt != "":
            self.add_history("system", user_prompt)

    def add_history(self, user: str, prompt: str):
        self.__history.append(f"{user.capitalize()}: {prompt} ")

        if len(self.__history) > self.__max_history:
            del self.__history[1]  # don't remove 0 because that is the main system prompt
            print("deleted some history")
        # todo: ask the ai to decide which should be removed?
        # todo: base this on the number of tokens in the context not just the # of emails

    def get_history(self):
        # todo: change this to be more dynamic and not hard-coded
        # the first item in history is always the main system prompt. add example  text to it randomly...
        history = self.__history
        history[0] += random.choice(self.__examples)

        return "".join(history).replace("SYSTEM:", "")

    def respond_to(self, prompt: str, retry: bool = False) -> [str, str]:
        start_clock = time.time()
        # add the user input prompt to the history and return the response
        self.add_history("user", prompt)
        # https://github.com/marella/ctransformers#property-llmconfig
        reply = self.llm(f"{self.get_history()} ASSISTANT:",
                         max_new_tokens=480, repetition_penalty=1.25, temperature=1.0)

        # we should consider checking for toxic stuff / filtering this output
        reply = self.purge(reply)
        self.add_history("assistant", reply)

        print(f"Processing time: {round(time.time() - start_clock, 2)}")
        return reply

    def purge(self, text: str) -> str:
        return text.strip()
    # return text.replace("<|im_start|>", "").replace("<|im_end|>", "").replace("kitboga", "")
