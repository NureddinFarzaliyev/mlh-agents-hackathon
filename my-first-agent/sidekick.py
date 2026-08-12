import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from backboard import BackboardClient


ASSISTANT_FILE = Path(__file__).with_name("sidekick.json")
SYSTEM_PROMPT = (
    "You are Sidekick, a fun and friendly personal chatbot. "
    "Be warm, upbeat, and helpful. Keep answers clear and conversational, "
    "and add a little playful personality when it fits."
)
GET_TIME_TOOL = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Get the current local date and time.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}


def load_assistant_id() -> str:
    if ASSISTANT_FILE.exists():
        try:
            data = json.loads(ASSISTANT_FILE.read_text(encoding="utf-8"))
            assistant_id = data["assistant_id"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            raise RuntimeError(
                f"{ASSISTANT_FILE.name} is invalid; fix or remove it before starting."
            )
        if not isinstance(assistant_id, str) or not assistant_id:
            raise RuntimeError(f"{ASSISTANT_FILE.name} does not contain a valid assistant_id.")
        return assistant_id

    raise RuntimeError("unreachable")


async def get_assistant_id(client: BackboardClient) -> str:
    if ASSISTANT_FILE.exists():
        assistant_id = load_assistant_id()
        await client.update_assistant(assistant_id, tools=[GET_TIME_TOOL])
        return assistant_id

    assistant = await client.create_assistant(
        name="Sidekick",
        system_prompt=SYSTEM_PROMPT,
        tools=[GET_TIME_TOOL],
    )
    assistant_id = str(assistant.assistant_id)
    ASSISTANT_FILE.write_text(
        json.dumps({"assistant_id": assistant_id}, indent=2) + "\n",
        encoding="utf-8",
    )
    return assistant_id


def get_time() -> dict[str, str]:
    now = datetime.now().astimezone()
    return {
        "local_time": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "iso_time": now.isoformat(),
    }


def dispatch_tool(name: str, arguments: dict) -> dict[str, str]:
    if name == "get_time":
        return get_time()
    return {"error": f"Unknown tool: {name}"}


async def send_message_with_tools(
    client: BackboardClient,
    message: str,
    assistant_id: str,
    thread_id,
):
    message_args = {
        "assistant_id": assistant_id,
        "memory": "Auto",
        "tools": [GET_TIME_TOOL],
    }
    if thread_id is not None:
        message_args["thread_id"] = thread_id

    response = await client.send_message(message, **message_args)
    while response.status == "REQUIRES_ACTION" and response.tool_calls:
        tool_outputs = []
        for tool_call in response.tool_calls:
            result = dispatch_tool(
                tool_call.function.name,
                tool_call.function.parsed_arguments,
            )
            tool_outputs.append(
                {
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(result),
                }
            )
        response = await client.submit_tool_outputs_simple(
            thread_id=response.thread_id,
            tool_outputs=tool_outputs,
        )
    return response


async def chat() -> None:
    api_key = os.environ.get("BACKBOARD_API_KEY")
    if not api_key:
        raise RuntimeError("BACKBOARD_API_KEY is not set.")

    client = BackboardClient(api_key=api_key)
    assistant_id = await get_assistant_id(client)
    thread_id = None

    while True:
        try:
            message = input()
        except EOFError:
            break

        if message.strip().lower() == "quit":
            break
        if not message.strip():
            continue

        response = await send_message_with_tools(
            client,
            message,
            assistant_id,
            thread_id,
        )
        thread_id = response.thread_id
        print(response.content, flush=True)


def main() -> None:
    try:
        asyncio.run(chat())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"sidekick: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
