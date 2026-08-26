from app.tools.base import ToolResult, tool

CDP_URL = "http://localhost:9222"


def _connect(sync_playwright):
    return sync_playwright().start()


@tool(
    name="list_browser_tabs",
    description=(
        "Lists all open tabs in the user's active Chrome session. Requires Chrome started "
        "with --remote-debugging-port=9222. Returns tab indexes with titles and URLs."
    ),
)
def list_browser_tabs() -> ToolResult:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            lines = [
                f"Tab {i}: '{page.title()}' -> {page.url}"
                for i, page in enumerate(context.pages)
            ]
            browser.close()
        if not lines:
            return ToolResult(success=True, message="No open tabs found.")
        return ToolResult(success=True, message="Open tabs:\n" + "\n".join(lines))
    except Exception as exc:
        return ToolResult(
            success=False,
            message=(
                f"Could not connect to Chrome ({exc}). "
                "Chrome must be running with --remote-debugging-port=9222."
            ),
        )


@tool(
    name="analyze_browser_tab",
    description=(
        "Lists clickable/typeable elements with CSS selectors for a tab (by index from "
        "list_browser_tabs). Always call this before interacting with a complex page."
    ),
)
def analyze_browser_tab(tab_index: int) -> ToolResult:
    js_script = """
    () => {
        const elements = Array.from(document.querySelectorAll('input, button, a, [role="button"], [role="searchbox"], textarea'));
        return elements.filter(el => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }).map(el => {
            let text = (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim();
            let selector = el.tagName.toLowerCase();
            if (el.id) selector += '#' + el.id;
            else if (el.className && typeof el.className === 'string') selector += '.' + el.className.split(' ').filter(c => c).join('.');
            const label = el.getAttribute('aria-label');
            if (label) selector += `[aria-label="${label}"]`;
            if (text.length > 50) text = text.substring(0, 50) + '...';
            return `Tag: ${el.tagName}, Label: "${text}", Selector: \`${selector}\``;
        }).slice(0, 40);
    }
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            if tab_index < 0 or tab_index >= len(context.pages):
                browser.close()
                return ToolResult(success=False, message=f"Invalid tab index {tab_index}.")
            elements = context.pages[tab_index].evaluate(js_script)
            browser.close()
        if not elements:
            return ToolResult(success=True, message="No interactive elements found on that page.")
        return ToolResult(success=True, message="\n".join(elements))
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not analyze the tab: {exc}")


@tool(
    name="interact_browser_tab",
    description=(
        "Performs an action on a browser tab: click a selector, fill text, press a key, or "
        "goto URL. Actions: 'click', 'fill', 'press', 'goto'."
    ),
)
def interact_browser_tab(tab_index: int, action: str, selector: str = "", text: str = "") -> ToolResult:
    if action not in ("click", "fill", "press", "goto"):
        return ToolResult(success=False, message=f"Unsupported action '{action}'.")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0]
            if tab_index < 0 or tab_index >= len(context.pages):
                browser.close()
                return ToolResult(success=False, message=f"Invalid tab index {tab_index}.")
            page = context.pages[tab_index]
            page.bring_to_front()

            if action == "click":
                page.click(selector)
                detail = f"Clicked {selector}"
            elif action == "fill":
                page.fill(selector, text)
                detail = f"Filled {selector}"
            elif action == "press":
                page.press(selector, text)
                detail = f"Pressed {text} on {selector}"
            else:
                page.goto(text)
                detail = f"Navigated to {text}"

            page.wait_for_timeout(1200)
            browser.close()
        return ToolResult(success=True, message=f"{detail} on tab {tab_index}.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Browser interaction failed: {exc}")
