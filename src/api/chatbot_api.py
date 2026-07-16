
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from myChatbot.agent import root_agent
from myChatbot.tools import close_tool_connections
from config import CHATBOT_API_KEY


MODEL_ID = "weather-assistant"




# -------------------------------------------------------------------
# ADK setup
# -------------------------------------------------------------------

session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name=root_agent.name,
    session_service=session_service,
)


# -------------------------------------------------------------------
# Application setup
# -------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

    # Close the shared HTTP client and database pool from tools.py.
    await close_tool_connections()


app = FastAPI(
    title="ADK Weather Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# Request models
# -------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage]
    stream: bool = False
    user: str | None = None



# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------

def verify_api_key(
    authorization: str | None,
) -> None:
    """
    Verify the Bearer token sent by Open WebUI.
    """

    if not CHATBOT_API_KEY:
        return

    expected_header = f"Bearer {CHATBOT_API_KEY}"

    if authorization != expected_header:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )


def safe_identifier(
    value: str,
    prefix: str,
) -> str:
    """
    Convert an external identifier into a safe ADK identifier.
    """

    cleaned = re.sub(
        r"[^a-zA-Z0-9_-]",
        "-",
        value,
    )

    cleaned = cleaned[:100]

    if cleaned:
        return cleaned

    return f"{prefix}-{uuid.uuid4().hex}"


async def ensure_session(
    user_id: str,
    session_id: str,
) -> None:
    """
    Create an ADK session if it does not already exist.
    """

    try:
        await session_service.create_session(
            app_name=root_agent.name,
            session_id=session_id,
            user_id=user_id,
        )
    except Exception:
        # The session most likely already exists.
        pass


async def run_agent(
    message: str,
    user_id: str,
    session_id: str,
) -> str:
    """
    Send one user message to the ADK root agent.
    """

    await ensure_session(
        user_id=user_id,
        session_id=session_id,
    )

    final_reply = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[
                types.Part(text=message),
            ],
        ),
    ):
        if (
            event.is_final_response()
            and event.content
            and event.content.parts
        ):
            final_reply = "".join(
                part.text or ""
                for part in event.content.parts
            )

    if not final_reply:
        return (
            "I couldn't prepare a response right now. "
            "Please try again."
        )

    return final_reply


# -------------------------------------------------------------------
# Basic endpoints
# -------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": "ADK Weather Assistant",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
    }


# -------------------------------------------------------------------
# OpenAI-compatible endpoints for Open WebUI
# -------------------------------------------------------------------

@app.get("/v1/models")
async def list_models(
    authorization: str | None = Header(default=None),
):
    """
    Tell Open WebUI which chatbot model is available.
    """

    verify_api_key(authorization)

    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "adk",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
    x_openwebui_chat_id: str | None = Header(default=None),
    x_openwebui_user_id: str | None = Header(default=None),
):
    """
    Receive OpenAI-compatible requests from Open WebUI.
    """

    verify_api_key(authorization)

    if request.model != MODEL_ID:
        raise HTTPException(
            status_code=404,
            detail="Model not found.",
        )

    user_messages = [
        message.content
        for message in request.messages
        if message.role == "user"
    ]

    if not user_messages:
        raise HTTPException(
            status_code=400,
            detail="A user message is required.",
        )

    # Open WebUI sends the full conversation history.
    # ADK already maintains its own session history, so send only
    # the latest user message to avoid duplicating the conversation.
    latest_message = user_messages[-1]

    user_id = safe_identifier(
        x_openwebui_user_id
        or request.user
        or "open-webui-user",
        prefix="user",
    )

    session_id = safe_identifier(
        x_openwebui_chat_id
        or f"session-{uuid.uuid4().hex}",
        prefix="session",
    )

    reply = await run_agent(
        message=latest_message,
        user_id=user_id,
        session_id=session_id,
    )

    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created_at = int(time.time())

    if request.stream:
        return create_streaming_response(
            reply=reply,
            completion_id=completion_id,
            created_at=created_at,
        )

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_at,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": reply,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def create_streaming_response(
    reply: str,
    completion_id: str,
    created_at: int,
) -> StreamingResponse:
    """
    Return the completed ADK response using OpenAI's SSE format.

    ADK finishes processing before this begins, so this is response
    compatibility rather than token-by-token ADK streaming.
    """

    async def event_generator():
        content_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_at,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": reply,
                    },
                    "finish_reason": None,
                }
            ],
        }

        final_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_at,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }

        yield f"data: {json.dumps(content_chunk)}\n\n"
        yield f"data: {json.dumps(final_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )

