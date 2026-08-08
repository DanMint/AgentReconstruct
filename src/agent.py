from langchain.agents import create_agent
from langchain.tools import tool
from langchain_ollama import ChatOllama

class Agent:
    def __init__(self, model_name:str = "minicpm-v4.5:latest", temp:int = 0, agent_prompt:str = "You are a helpful assistant") -> None:
        self.model = model_name
        self.tempeture = temp
        self.system_prompt = agent_prompt
        
        self.model = ChatOllama(
            model = self.model,
            tempeture = self.tempeture,
            # base_url = "http://127.0.0.1:9000"
        )

        self.agent = create_agent(
            model = self.model,
            tools = [],
            system_prompt = self.system_prompt,
        )

    def invoke(self, role: str = "user",messages: str = "") -> dict:
        return self.agent.invoke(
            {
                "messages": [
                    {
                        "role": role,
                        "content": messages,
                    }
                ]
            }
        )

    @property
    def getAgent(self):
        return self.agent

def main():
    agent = Agent(agent_prompt="")
    result = agent.invoke(messages = "What it do lil boo?")

    print(result)

if __name__ == "__main__":
    main()