from fastapi import APIRouter
from pydantic import BaseModel

from app.ai.agent.supervisor import process_text

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    text: str


@router.post("/chat")
async def chat(request: ChatRequest) -> dict:
    result = await process_text(request.text, source="api")
    return {
        "reply": result.reply,
        "language": result.language,
        "mode": result.mode,
        "tool_used": result.tool_used,
    }
