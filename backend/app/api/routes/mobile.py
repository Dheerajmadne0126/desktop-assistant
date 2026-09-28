from fastapi import APIRouter, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import base64

from app.mobile.auth import mobile_auth, MobileDevice, MobileSession, PairingSession, PermissionLevel
from app.core.logging import get_logger

logger = get_logger("mobile_api")

router = APIRouter(prefix="/mobile", tags=["mobile"])


class PairingRequest(BaseModel):
    device_name: str


class PairingResponse(BaseModel):
    session_token: str
    qr_code_base64: str
    expires_at: str


class DeviceResponse(BaseModel):
    id: str
    name: str
    device_id: str
    status: str
    paired_at: Optional[str]
    last_seen: Optional[str]
    expires_at: Optional[str]


class SessionResponse(BaseModel):
    session_token: str
    expires_at: str


class PermissionCheckRequest(BaseModel):
    tool_name: str
    session_token: str


class PermissionCheckResponse(BaseModel):
    allowed: bool
    level: str
    requires_confirmation: bool


class ToolListResponse(BaseModel):
    allowed_tools: List[str]
    max_level: str


class WebSocketMessage(BaseModel):
    type: str
    payload: Dict[str, Any] = {}


def get_session_token_from_header(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return auth[7:]


async def get_current_session(session_token: str = Depends(get_session_token_from_header)) -> MobileSession:
    session = await mobile_auth.validate_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session


async def get_current_device(session: MobileSession = Depends(get_current_session)) -> MobileDevice:
    device = await mobile_auth.get_device(session.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.status != "paired":
        raise HTTPException(status_code=403, detail="Device not paired or revoked")
    return device


@router.post("/pair/start", response_model=PairingResponse)
async def start_pairing(request: PairingRequest) -> PairingResponse:
    session = await mobile_auth.create_pairing_session(request.device_name)
    return PairingResponse(
        session_token=session.session_token,
        qr_code_base64=session.qr_code_data,
        expires_at=session.expires_at.isoformat(),
    )


@router.get("/pair/status/{session_token}")
async def check_pairing_status(session_token: str):
    session = await mobile_auth.get_pairing_session(session_token)
    if not session:
        raise HTTPException(status_code=404, detail="Pairing session not found")
    
    return {
        "status": session.status,
        "device_id": session.device_id,
        "expires_at": session.expires_at.isoformat(),
    }


@router.post("/pair/complete")
async def complete_pairing(session_token: str, public_key: str):
    device = await mobile_auth.complete_pairing(session_token, public_key)
    if not device:
        raise HTTPException(status_code=400, detail="Invalid or expired pairing session")
    
    mobile_session = await mobile_auth.create_session(device.device_id)
    
    return {
        "device": DeviceResponse(
            id=str(device.id),
            name=device.name,
            device_id=device.device_id,
            status=device.status,
            paired_at=device.paired_at.isoformat() if device.paired_at else None,
            last_seen=device.last_seen.isoformat() if device.last_seen else None,
            expires_at=device.expires_at.isoformat() if device.expires_at else None,
        ),
        "session": SessionResponse(
            session_token=mobile_session.session_token,
            expires_at=mobile_session.expires_at.isoformat(),
        ),
    }


@router.get("/devices", response_model=List[DeviceResponse])
async def list_devices(current_device: MobileDevice = Depends(get_current_device)):
    devices = await mobile_auth.list_devices()
    return [
        DeviceResponse(
            id=str(d.id),
            name=d.name,
            device_id=d.device_id,
            status=d.status,
            paired_at=d.paired_at.isoformat() if d.paired_at else None,
            last_seen=d.last_seen.isoformat() if d.last_seen else None,
            expires_at=d.expires_at.isoformat() if d.expires_at else None,
        )
        for d in devices
    ]


@router.get("/devices/me", response_model=DeviceResponse)
async def get_current_device_info(current_device: MobileDevice = Depends(get_current_device)):
    return DeviceResponse(
        id=str(current_device.id),
        name=current_device.name,
        device_id=current_device.device_id,
        status=current_device.status,
        paired_at=current_device.paired_at.isoformat() if current_device.paired_at else None,
        last_seen=current_device.last_seen.isoformat() if current_device.last_seen else None,
        expires_at=current_device.expires_at.isoformat() if current_device.expires_at else None,
    )


@router.post("/sessions", response_model=SessionResponse)
async def create_session(request: Request, current_device: MobileDevice = Depends(get_current_device)):
    ip = request.client.host if request.client else None
    ua = request.headers.get("User-Agent")
    session = await mobile_auth.create_session(current_device.device_id, ip, ua)
    return SessionResponse(
        session_token=session.session_token,
        expires_at=session.expires_at.isoformat(),
    )


@router.delete("/sessions/me")
async def revoke_current_session(session: MobileSession = Depends(get_current_session)):
    await mobile_auth.revoke_session(session.session_token)
    return {"success": True, "message": "Session revoked"}


@router.delete("/devices/me")
async def revoke_current_device(current_device: MobileDevice = Depends(get_current_device)):
    await mobile_auth.revoke_device(current_device.device_id)
    return {"success": True, "message": "Device revoked"}


@router.post("/permission/check", response_model=PermissionCheckResponse)
async def check_permission(request: PermissionCheckRequest):
    session = await mobile_auth.validate_session(request.session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    rule = mobile_auth.get_permission_rule(request.tool_name)
    if not rule:
        return PermissionCheckResponse(
            allowed=False,
            level="unknown",
            requires_confirmation=True,
        )
    
    return PermissionCheckResponse(
        allowed=True,
        level=rule.level.value,
        requires_confirmation=rule.requires_confirmation,
    )


@router.get("/permissions/tools", response_model=ToolListResponse)
async def list_allowed_tools(
    max_level: PermissionLevel = PermissionLevel.HIGH,
    current_device: MobileDevice = Depends(get_current_device)
):
    allowed = mobile_auth.get_allowed_tools_for_level(max_level)
    return ToolListResponse(
        allowed_tools=sorted(allowed),
        max_level=max_level.value,
    )


@router.websocket("/ws")
async def mobile_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("Mobile WebSocket connected")
    
    session_token = None
    session = None
    
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "auth":
                token = data.get("token")
                if token:
                    session = await mobile_auth.validate_session(token)
                    if session:
                        session_token = token
                        await websocket.send_json({
                            "type": "auth_response",
                            "success": True,
                            "device_id": session.device_id,
                        })
                    else:
                        await websocket.send_json({
                            "type": "auth_response",
                            "success": False,
                            "error": "Invalid or expired session",
                        })
                else:
                    await websocket.send_json({
                        "type": "auth_response",
                        "success": False,
                        "error": "Token required",
                    })
            
            elif msg_type == "permission_check":
                tool_name = data.get("tool_name")
                if not tool_name:
                    await websocket.send_json({"type": "permission_response", "success": False, "error": "tool_name required"})
                    continue
                
                rule = mobile_auth.get_permission_rule(tool_name)
                await websocket.send_json({
                    "type": "permission_response",
                    "tool_name": tool_name,
                    "allowed": rule is not None,
                    "level": rule.level.value if rule else "unknown",
                    "requires_confirmation": rule.requires_confirmation if rule else True,
                })
            
            elif msg_type == "execute_tool":
                if not session_token:
                    await websocket.send_json({"type": "tool_response", "success": False, "error": "Not authenticated"})
                    continue
                
                tool_name = data.get("tool_name")
                args = data.get("args", {})
                
                if not tool_name:
                    await websocket.send_json({"type": "tool_response", "success": False, "error": "tool_name required"})
                    continue
                
                rule = mobile_auth.get_permission_rule(tool_name)
                if not rule:
                    await websocket.send_json({"type": "tool_response", "success": False, "error": f"Tool {tool_name} not allowed"})
                    continue
                
                if rule.requires_confirmation:
                    await websocket.send_json({
                        "type": "tool_response",
                        "success": False,
                        "error": "Confirmation required",
                        "requires_confirmation": True,
                    })
                    continue
                
                from app.tools.registry import registry
                result = await registry.execute(tool_name, args, triggered_by="mobile", conversation_id=None)
                
                await websocket.send_json({
                    "type": "tool_response",
                    "success": result.success,
                    "message": result.message,
                    "data": result.data,
                })
            
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            
            else:
                await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
    
    except WebSocketDisconnect:
        logger.info("Mobile WebSocket disconnected")
    except Exception as exc:
        logger.warning("Mobile WebSocket error: %s", exc)
    finally:
        if session_token:
            logger.info("Mobile WebSocket closed for session: %s", session_token[:16])