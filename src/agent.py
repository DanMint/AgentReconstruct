from langchain.agents import create_agent
from langchain_ollama import ChatOllama
import uuid


class Agent:

    def __init__(self, tools=None, trace_id: str | None = None, model_name: str = "minicpm-v4.5:latest", temp: float = 0, agent_prompt: str = "You are a helpful assistant") -> None:
        # Trace ID
        if trace_id is None:
            self.trace_id = str(uuid.uuid4())
        else:
            self.trace_id = trace_id

        # LLM
        self.model = ChatOllama(
            model=model_name,

            # Notice spelling:
            temperature=temp,

            # ALL LLM traffic goes through LLM Gateway
            base_url="http://127.0.0.1:9000",

            client_kwargs={
                "headers": {
                    "X-Trace-ID": self.trace_id
                }
            },
        )


        # Tools
        if tools is None:
            tools = []

        self.tools = tools

        # LangChain Agent
        self.agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=agent_prompt,
        )


    async def invoke(self, role: str = "user", messages: str = "") -> dict:
        return await self.agent.ainvoke(
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