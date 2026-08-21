from langchain.agents import create_agent
from langchain_ollama import ChatOllama

import uuid
import httpx


RECORDER_URL = "http://127.0.0.1:9100"


class Agent:

    def __init__(
        self,
        tools=None,
        trace_id: str | None = None,
        model_name: str = "minicpm-v4.5:latest",
        temp: float = 0,
        agent_prompt: str = "You are a helpful assistant"
    ) -> None:

        # trace ID
        if trace_id is None:
            self.trace_id = str(uuid.uuid4())
        else:
            self.trace_id = trace_id

        # LLM
        self.model = ChatOllama(
            model=model_name,
            temperature=temp,

            # All LLM traffic goes through LLM Gateway
            base_url="http://127.0.0.1:9000",

            # Propagate trace ID to LLM Gateway
            client_kwargs={
                "headers": {
                    "X-Trace-ID": self.trace_id
                }
            },
        )

        # tools
        if tools is None:
            tools = []

        self.tools = tools

        # LangChain Agent
        self.agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=agent_prompt,
        )

    # record Host-Level Event
    async def _record_host_event(
        self,
        event_type: str,
        source: str,
        destination: str,
        payload: dict
    ) -> None:

        """
        Send an event observed at the Agent Host
        to the trusted Event Recorder.

        source/destination describe the actual
        execution event, not the logging connection.
        """

        async with httpx.AsyncClient(
            timeout=30
        ) as client:

            response = await client.post(
                f"{RECORDER_URL}/api/events",

                json={
                    "trace_id": self.trace_id,
                    "event_type": event_type,
                    "source": source,
                    "destination": destination,
                    "payload": payload,
                }
            )

            # recorder must acknowledge event
            response.raise_for_status()

    # invoke Agent
    async def invoke(
        self,
        role: str = "user",
        messages: str = ""
    ) -> dict:
        # ----------------------------------------------------
        # TRACE_START
        #
        # Lifecycle marker indicating that the Agent Host
        # has begun processing this execution
        # ----------------------------------------------------

        await self._record_host_event(
            event_type="TRACE_START",
            source="agent_host",
            destination="agent_host",
            payload={}
        )


        # ----------------------------------------------------
        # USER_INPUT
        #
        # Actual communication:
        #
        # User -> Agent Host
        # ----------------------------------------------------

        await self._record_host_event(
            event_type="USER_INPUT",
            source="user",
            destination="agent_host",
            payload={
                "role": role,
                "content": messages,
            }
        )

        # ----------------------------------------------------
        # Execute Agent
        #
        # The LangChain agent can now:
        #
        # Agent Host
        #     -> LLM Gateway
        #     -> Ollama
        #
        # and:
        #
        # Agent Host
        #     -> MCP Gateway
        #     -> MCP Server
        #     -> Tool
        # ----------------------------------------------------
        result = await self.agent.ainvoke(
            {
                "messages": [
                    {
                        "role": role,
                        "content": messages,
                    }
                ]
            }
        )

        # get final message produced by the Agent Host
        final_message = result["messages"][-1]

        final_content = final_message.content

        # ----------------------------------------------------
        # FINAL_RESPONSE
        #
        # Actual communication:
        #
        # Agent Host -> User
        # ----------------------------------------------------

        await self._record_host_event(
            event_type="FINAL_RESPONSE",
            source="agent_host",
            destination="user",
            payload={
                "content": final_content
            }
        )

        # ----------------------------------------------------
        # TRACE_END
        #
        # Lifecycle marker indicating that execution
        # has completed.
        # ----------------------------------------------------
        await self._record_host_event(
            event_type="TRACE_END",
            source="agent_host",
            destination="agent_host",
            payload={}
        )

        return result

    @property
    def getAgent(self):
        return self.agent