import secrets
import hashlib
import time
import qrcode
import io
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Set
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select, update, delete, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import database
from app.db.base import Base, TimestampMixin, UuidPkMixin

logger = get_logger("mobile_auth")


class DeviceStatus(str, Enum):
    PENDING = "pending"
    PAIRED = "paired"
    REVOKED = "revoked"
    EXPIRED = "expired"


class PermissionLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class PermissionRule:
    tool_name: str
    level: PermissionLevel
    description: str
    requires_confirmation: bool = False


DEFAULT_PERMISSIONS: Dict[str, PermissionRule] = {
    # LOW - Safe read-only operations
    "get_system_time": PermissionRule("get_system_time", PermissionLevel.LOW, "Get current time", False),
    "system_info": PermissionRule("system_info", PermissionLevel.LOW, "System information", False),
    "list_directory": PermissionRule("list_directory", PermissionLevel.LOW, "List files", False),
    "read_file": PermissionRule("read_file", PermissionLevel.LOW, "Read file", False),
    "search_files": PermissionRule("search_files", PermissionLevel.LOW, "Search files", False),
    "open_file": PermissionRule("open_file", PermissionLevel.LOW, "Open file", False),
    "web_search": PermissionRule("web_search", PermissionLevel.LOW, "Web search", False),
    "open_website": PermissionRule("open_website", PermissionLevel.LOW, "Open website", False),
    "youtube_play": PermissionRule("youtube_play", PermissionLevel.LOW, "Play YouTube", False),
    "list_browser_tabs": PermissionRule("list_browser_tabs", PermissionLevel.LOW, "List browser tabs", False),
    "analyze_browser_tab": PermissionRule("analyze_browser_tab", PermissionLevel.LOW, "Analyze tab", False),
    "browser_open": PermissionRule("browser_open", PermissionLevel.LOW, "Open browser", False),
    "browser_search_and_extract": PermissionRule("browser_search_and_extract", PermissionLevel.LOW, "Search and extract", False),
    "browser_extract_structured": PermissionRule("browser_extract_structured", PermissionLevel.LOW, "Extract structured", False),
    "get_project_summary": PermissionRule("get_project_summary", PermissionLevel.LOW, "Project summary", False),
    "list_projects": PermissionRule("list_projects", PermissionLevel.LOW, "List projects", False),
    "find_project": PermissionRule("find_project", PermissionLevel.LOW, "Find project", False),
    "list_applications": PermissionRule("list_applications", PermissionLevel.LOW, "List apps", False),
    "take_screenshot": PermissionRule("take_screenshot", PermissionLevel.LOW, "Screenshot", False),
    "lock_workstation": PermissionRule("lock_workstation", PermissionLevel.LOW, "Lock workstation", False),
    "recall_information": PermissionRule("recall_information", PermissionLevel.LOW, "Recall memory", False),
    "list_schedules": PermissionRule("list_schedules", PermissionLevel.LOW, "List schedules", False),
    "search_in_files": PermissionRule("search_in_files", PermissionLevel.LOW, "Search code", False),
    "open_project_in_vscode": PermissionRule("open_project_in_vscode", PermissionLevel.LOW, "Open in VS Code", False),
    "run_dev_command": PermissionRule("run_dev_command", PermissionLevel.LOW, "Run dev command", False),
    "check_unread_emails": PermissionRule("check_unread_emails", PermissionLevel.LOW, "Check emails", False),

    # MEDIUM - Operations that modify state but are generally safe
    "open_application": PermissionRule("open_application", PermissionLevel.MEDIUM, "Open application", False),
    "focus_application": PermissionRule("focus_application", PermissionLevel.MEDIUM, "Focus application", False),
    "restart_application": PermissionRule("restart_application", PermissionLevel.MEDIUM, "Restart application", False),
    "control_volume": PermissionRule("control_volume", PermissionLevel.MEDIUM, "Control volume", False),
    "set_brightness": PermissionRule("set_brightness", PermissionLevel.MEDIUM, "Set brightness", False),
    "write_file": PermissionRule("write_file", PermissionLevel.MEDIUM, "Write file", True),
    "rename_file": PermissionRule("rename_file", PermissionLevel.MEDIUM, "Rename file", False),
    "move_file": PermissionRule("move_file", PermissionLevel.MEDIUM, "Move file", True),
    "open_project": PermissionRule("open_project", PermissionLevel.MEDIUM, "Open project in IDE", False),
    "open_project_terminal": PermissionRule("open_project_terminal", PermissionLevel.MEDIUM, "Open project terminal", False),
    "run_project_command": PermissionRule("run_project_command", PermissionLevel.MEDIUM, "Run project command", True),
    "create_daily_routine": PermissionRule("create_daily_routine", PermissionLevel.MEDIUM, "Create routine", True),
    "set_reminder": PermissionRule("set_reminder", PermissionLevel.MEDIUM, "Set reminder", False),
    "set_alarm": PermissionRule("set_alarm", PermissionLevel.MEDIUM, "Set alarm", False),
    "set_timer": PermissionRule("set_timer", PermissionLevel.MEDIUM, "Set timer", False),
    "send_email": PermissionRule("send_email", PermissionLevel.MEDIUM, "Send email", True),
    "remember_fact": PermissionRule("remember_fact", PermissionLevel.MEDIUM, "Remember fact", False),
    "read_document_into_memory": PermissionRule("read_document_into_memory", PermissionLevel.MEDIUM, "Read document", False),
    "browser_automate": PermissionRule("browser_automate", PermissionLevel.MEDIUM, "Browser automation", True),
    "interact_browser_tab": PermissionRule("interact_browser_tab", PermissionLevel.MEDIUM, "Interact with tab", True),
    "cancel_schedule": PermissionRule("cancel_schedule", PermissionLevel.MEDIUM, "Cancel schedule", False),

    # HIGH - Destructive or system-level operations
    "close_application": PermissionRule("close_application", PermissionLevel.HIGH, "Close application", True),
    "delete_file": PermissionRule("delete_file", PermissionLevel.HIGH, "Delete file", True),
    "shutdown_pc": PermissionRule("shutdown_pc", PermissionLevel.HIGH, "Shutdown PC", True),
    "restart_pc": PermissionRule("restart_pc", PermissionLevel.HIGH, "Restart PC", True),
    "abort_shutdown": PermissionRule("abort_shutdown", PermissionLevel.HIGH, "Abort shutdown", True),
}


class MobileDevice(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "mobile_devices"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=DeviceStatus.PENDING.value, nullable=False)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    device_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PairingSession(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "pairing_sessions"

    session_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    qr_code_data: Mapped[str] = mapped_column(Text, nullable=False)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class MobileSession(Base, UuidPkMixin, TimestampMixin):
    __tablename__ = "mobile_sessions"

    session_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


from sqlalchemy import String, Text, DateTime


def generate_device_id() -> str:
    return secrets.token_urlsafe(32)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def generate_pairing_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class MobileAuthService:
    def __init__(self):
        self.settings = get_settings()
        self._permission_cache: Dict[str, PermissionRule] = DEFAULT_PERMISSIONS.copy()

    async def create_pairing_session(self, device_name: str, expires_in_minutes: int = 5) -> PairingSession:
        session_token = generate_pairing_token()
        qr_data = f"jarvis://pair?token={session_token}&host={self.settings.server_host}:{self.settings.server_port}"
        
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
        
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()
        
        session = PairingSession(
            session_token=session_token,
            qr_code_data=qr_b64,
            device_name=device_name,
            expires_at=expires_at,
        )
        
        async with database.session() as session_db:
            session_db.add(session)
            await session_db.commit()
            await session_db.refresh(session)
        
        logger.info("Created pairing session for device: %s", device_name)
        return session

    async def complete_pairing(self, session_token: str, device_public_key: str) -> Optional[MobileDevice]:
        async with database.session() as session_db:
            stmt = select(PairingSession).where(PairingSession.session_token == session_token)
            session = (await session_db.execute(stmt)).scalar_one_or_none()
            
            if not session:
                return None
            
            if session.status != "pending":
                return None
            
            if session.expires_at < datetime.now(timezone.utc):
                session.status = "expired"
                await session_db.commit()
                return None
            
            device_id = generate_device_id()
            device = MobileDevice(
                name=session.device_name,
                device_id=device_id,
                public_key=device_public_key,
                status=DeviceStatus.PAIRED.value,
                paired_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=365),
                permissions={},
            )
            
            session.status = "completed"
            session.completed_at = datetime.now(timezone.utc)
            session.device_id = device_id
            
            session_db.add(device)
            await session_db.commit()
            await session_db.refresh(device)
            
            logger.info("Device paired successfully: %s (%s)", device.name, device_id)
            return device

    async def get_pairing_session(self, session_token: str) -> Optional[PairingSession]:
        async with database.session() as session_db:
            stmt = select(PairingSession).where(PairingSession.session_token == session_token)
            return (await session_db.execute(stmt)).scalar_one_or_none()

    async def get_device(self, device_id: str) -> Optional[MobileDevice]:
        async with database.session() as session_db:
            stmt = select(MobileDevice).where(MobileDevice.device_id == device_id)
            return (await session_db.execute(stmt)).scalar_one_or_none()

    async def create_session(self, device_id: str, ip_address: str = None, user_agent: str = None) -> MobileSession:
        session_token = generate_session_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        
        session = MobileSession(
            session_token=session_token,
            device_id=device_id,
            expires_at=expires_at,
            last_activity=datetime.now(timezone.utc),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        
        async with database.session() as session_db:
            session_db.add(session)
            await session_db.commit()
            await session_db.refresh(session)
        
        logger.info("Created mobile session for device: %s", device_id)
        return session

    async def validate_session(self, session_token: str) -> Optional[MobileSession]:
        async with database.session() as session_db:
            stmt = select(MobileSession).where(
                MobileSession.session_token == session_token,
                MobileSession.is_active == True,
                MobileSession.expires_at > datetime.now(timezone.utc)
            )
            session = (await session_db.execute(stmt)).scalar_one_or_none()
            
            if session:
                session.last_activity = datetime.now(timezone.utc)
                await session_db.commit()
            
            return session

    async def revoke_session(self, session_token: str) -> bool:
        async with database.session() as session_db:
            stmt = select(MobileSession).where(MobileSession.session_token == session_token)
            session = (await session_db.execute(stmt)).scalar_one_or_none()
            
            if session:
                session.is_active = False
                await session_db.commit()
                return True
            return False

    async def revoke_device(self, device_id: str) -> bool:
        async with database.session() as session_db:
            stmt = select(MobileDevice).where(MobileDevice.device_id == device_id)
            device = (await session_db.execute(stmt)).scalar_one_or_none()
            
            if device:
                device.status = DeviceStatus.REVOKED.value
                await session_db.commit()
                
                await session_db.execute(
                    update(MobileSession)
                    .where(MobileSession.device_id == device_id)
                    .values(is_active=False)
                )
                await session_db.commit()
                return True
            return False

    async def list_devices(self) -> List[MobileDevice]:
        async with database.session() as session_db:
            stmt = select(MobileDevice).where(MobileDevice.status == DeviceStatus.PAIRED.value)
            return list((await session_db.execute(stmt)).scalars())

    def get_permission_rule(self, tool_name: str) -> Optional[PermissionRule]:
        return self._permission_cache.get(tool_name)

    def get_tool_permission_level(self, tool_name: str) -> PermissionLevel:
        rule = self._permission_cache.get(tool_name)
        return rule.level if rule else PermissionLevel.HIGH

    def requires_confirmation(self, tool_name: str) -> bool:
        rule = self._permission_cache.get(tool_name)
        return rule.requires_confirmation if rule else True

    def get_allowed_tools_for_level(self, max_level: PermissionLevel) -> Set[str]:
        levels = [PermissionLevel.LOW]
        if max_level in (PermissionLevel.MEDIUM, PermissionLevel.HIGH):
            levels.append(PermissionLevel.MEDIUM)
        if max_level == PermissionLevel.HIGH:
            levels.append(PermissionLevel.HIGH)
        
        return {name for name, rule in self._permission_cache.items() if rule.level in levels}


mobile_auth = MobileAuthService()