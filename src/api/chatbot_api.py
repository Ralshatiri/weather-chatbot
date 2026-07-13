#  uvicorn api.chatbot_api:app --reload

from fastapi import FastAPI
import asyncio
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from myChatbot.agent import root_agent
from pydantic import BaseModel

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      
    allow_methods=["*"],
    allow_headers=["*"],
)

session_service = InMemorySessionService()

runner = Runner(
    agent=root_agent,
    app_name=root_agent.name,
    session_service=session_service
)

USER_ID = "ID2"

class ChatRequest(BaseModel):
    message:str
    session_id:str


@app.post("/chat")
async def chat(req : ChatRequest):

    try:
        await session_service.create_session(
            app_name=root_agent.name,
            session_id=req.session_id,
            user_id=USER_ID
        )
    except Exception:
        pass

    final = ""
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=req.session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=req.message)]),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final = event.content.parts[0].text

    return {"reply": final}
    