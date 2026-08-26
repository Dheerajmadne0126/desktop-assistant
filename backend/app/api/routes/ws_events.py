import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import event_bus
from app.core.logging import get_logger
from app.core.state import state_machine

logger = get_logger("ws")

router = APIRouter(tags=["events"])


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = event_bus.subscribe()
    logger.info("Dashboard WebSocket connected.")
    try:
        await websocket.send_json(
            {
                "type": "state_change",
                "state": state_machine.state.value,
                "message": "Connected",
            }
        )
        while True:
            receive_task = asyncio.create_task(websocket.receive_text())
            publish_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {receive_task, publish_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

            if receive_task in done:
                try:
                    msg = json.loads(receive_task.result())
                except (json.JSONDecodeError, ValueError):
                    continue
                msg_type = msg.get("type")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "trigger_listen":
                    from app.voice.pipeline import voice_pipeline

                    started = voice_pipeline.trigger_manual_listen()
                    await websocket.send_json(
                        {"type": "listen_ack", "started": started}
                    )

            if publish_task in done:
                event = publish_task.result()
                await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket disconnected.")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        event_bus.unsubscribe(queue)
