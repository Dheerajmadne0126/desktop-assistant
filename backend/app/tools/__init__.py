from app.core.logging import get_logger
from app.tools.browser.tabs_cdp import (
    analyze_browser_tab,
    interact_browser_tab,
    list_browser_tabs,
)
from app.tools.browser.web import open_website, web_search, youtube_play
from app.tools.comms.email import check_unread_emails, send_email
from app.tools.desktop.apps import (
    close_application,
    focus_application,
    open_application,
    restart_application,
)
from app.tools.desktop.power import (
    abort_shutdown,
    control_volume,
    restart_pc,
    set_brightness,
    shutdown_pc,
)
from app.tools.filesystem.files import (
    delete_file,
    list_directory,
    move_file,
    open_file,
    read_file,
    rename_file,
    search_files,
    write_file,
)
from app.tools.memory_ops import (
    read_document_into_memory,
    recall_information,
    remember_fact,
)
from app.tools.devtools.dev import (
    open_project_in_vscode,
    run_dev_command,
    search_in_files,
)
from app.tools.schedule_tools import (
    cancel_schedule,
    create_daily_routine,
    list_schedules,
    set_alarm,
    set_reminder,
    set_timer,
)
from app.tools.registry import registry
from app.tools.system.sysctl import (
    get_system_time,
    lock_workstation,
    system_info,
    take_screenshot,
)

logger = get_logger("tools")

_ALL = [
    get_system_time,
    system_info,
    take_screenshot,
    lock_workstation,
    open_application,
    close_application,
    focus_application,
    restart_application,
    shutdown_pc,
    restart_pc,
    abort_shutdown,
    control_volume,
    set_brightness,
    web_search,
    open_website,
    youtube_play,
    list_browser_tabs,
    analyze_browser_tab,
    interact_browser_tab,
    list_directory,
    read_file,
    search_files,
    write_file,
    delete_file,
    open_file,
    rename_file,
    move_file,
    check_unread_emails,
    send_email,
    remember_fact,
    recall_information,
    read_document_into_memory,
    run_dev_command,
    search_in_files,
    open_project_in_vscode,
    set_reminder,
    set_alarm,
    set_timer,
    create_daily_routine,
    list_schedules,
    cancel_schedule,
]

_registered = False


def register_all_tools() -> None:
    global _registered
    if _registered:
        return
    for t in _ALL:
        if registry.get(t.name) is None:
            registry.register(t)
    logger.info("Tool registry loaded with %d tools.", len(registry.all_tools()))
    _registered = True
