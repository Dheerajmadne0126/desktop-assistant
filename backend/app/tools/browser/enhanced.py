import urllib.parse
import asyncio
from typing import Optional, List, Dict, Any

from app.tools.base import ToolResult, tool
from app.core.logging import get_logger

logger = get_logger("browser_enhanced")

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


@tool(
    name="browser_open",
    description=(
        "Opens a URL in a headless browser and returns the page content. "
        "Useful for scraping JavaScript-heavy sites that regular HTTP requests can't handle. "
        "Returns the page HTML/text content and optionally a screenshot."
    ),
)
async def browser_open(
    url: str,
    wait_for: str = "networkidle",
    timeout: int = 30000,
    screenshot: bool = False,
    return_html: bool = True
) -> ToolResult:
    if not PLAYWRIGHT_AVAILABLE:
        return ToolResult(success=False, message="Playwright not available. Install playwright and run 'playwright install chromium'.")
    
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.goto(url, wait_until=wait_for, timeout=timeout)
            
            result_data = {}
            
            if return_html:
                content = await page.content()
                result_data["html"] = content[:50000]
            
            text = await page.inner_text("body")
            result_data["text"] = text[:10000]
            
            title = await page.title()
            result_data["title"] = title
            result_data["url"] = page.url
            
            if screenshot:
                screenshot_bytes = await page.screenshot(full_page=True)
                import base64
                result_data["screenshot_b64"] = base64.b64encode(screenshot_bytes).decode()
            
            await browser.close()
            
            msg = f"Opened {url}\nTitle: {title}"
            if return_html:
                msg += f"\nHTML length: {len(result_data.get('html', ''))}"
            msg += f"\nText length: {len(result_data.get('text', ''))}"
            
            return ToolResult(success=True, message=msg, data=result_data)
            
    except Exception as exc:
        logger.warning("browser_open failed: %s", exc)
        return ToolResult(success=False, message=f"Browser open failed: {exc}")


@tool(
    name="browser_search_and_extract",
    description=(
        "Searches the web for a query, opens the top results, and extracts structured content. "
        "Returns a summary of each result with extracted text content. "
        "Useful for research tasks where you need to read multiple sources."
    ),
)
async def browser_search_and_extract(
    query: str,
    max_results: int = 3,
    extract_depth: str = "summary"
) -> ToolResult:
    if not PLAYWRIGHT_AVAILABLE:
        return ToolResult(success=False, message="Playwright not available.")
    
    try:
        from ddgs import DDGS
        
        # First get search results
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        
        if not results:
            return ToolResult(success=True, message=f"No results found for '{query}'.")
        
        # Open each result and extract content
        extracted = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            for i, result in enumerate(results):
                url = result.get("href") or result.get("url")
                if not url:
                    continue
                
                try:
                    page = await browser.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    
                    title = await page.title()
                    text = await page.inner_text("body")
                    
                    if extract_depth == "full":
                        content = text[:15000]
                    else:
                        content = text[:3000]
                    
                    extracted.append({
                        "index": i + 1,
                        "title": title,
                        "url": url,
                        "source_title": result.get("title", ""),
                        "source_snippet": result.get("body", "")[:300],
                        "content": content,
                    })
                    
                    await page.close()
                    
                except Exception as exc:
                    logger.debug("Failed to extract from %s: %s", url, exc)
                    extracted.append({
                        "index": i + 1,
                        "title": result.get("title", "Failed"),
                        "url": url,
                        "error": str(exc),
                    })
            
            await browser.close()
        
        if not extracted:
            return ToolResult(success=True, message="No content could be extracted from results.")
        
        # Build summary message
        lines = [f"Search: '{query}' - Extracted {len(extracted)} results:\n"]
        for item in extracted:
            if "error" in item:
                lines.append(f"{item['index']}. {item['title']} - ERROR: {item['error']}")
            else:
                lines.append(f"{item['index']}. {item['title']} ({item['url']})")
                lines.append(f"   Source: {item['source_snippet'][:100]}...")
                lines.append(f"   Content: {item['content'][:200]}...")
                lines.append("")
        
        return ToolResult(
            success=True,
            message="\n".join(lines),
            data={"query": query, "results": extracted},
        )
        
    except Exception as exc:
        logger.warning("browser_search_and_extract failed: %s", exc)
        return ToolResult(success=False, message=f"Search and extract failed: {exc}")


@tool(
    name="browser_automate",
    description=(
        "Performs a sequence of browser actions programmatically. "
        "Actions: goto, click, fill, wait, evaluate, screenshot, pdf. "
        "Provide a list of action objects. Useful for form filling, "
        "multi-step workflows, and complex interactions."
    ),
)
async def browser_automate(
    actions: List[Dict[str, Any]],
    headless: bool = True,
    viewport: Optional[Dict[str, int]] = None
) -> ToolResult:
    if not PLAYWRIGHT_AVAILABLE:
        return ToolResult(success=False, message="Playwright not available.")
    
    if not actions:
        return ToolResult(success=False, message="No actions provided.")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            page = await browser.new_page()
            
            if viewport:
                await page.set_viewport_size(viewport)
            
            results = []
            
            for i, action in enumerate(actions):
                action_type = action.get("type")
                
                try:
                    if action_type == "goto":
                        url = action.get("url")
                        wait = action.get("wait", "networkidle")
                        timeout = action.get("timeout", 30000)
                        await page.goto(url, wait_until=wait, timeout=timeout)
                        results.append({"step": i, "action": "goto", "url": url, "success": True})
                    
                    elif action_type == "click":
                        selector = action.get("selector")
                        await page.click(selector)
                        results.append({"step": i, "action": "click", "selector": selector, "success": True})
                    
                    elif action_type == "fill":
                        selector = action.get("selector")
                        value = action.get("value", "")
                        await page.fill(selector, value)
                        results.append({"step": i, "action": "fill", "selector": selector, "success": True})
                    
                    elif action_type == "type":
                        selector = action.get("selector")
                        value = action.get("value", "")
                        delay = action.get("delay", 50)
                        await page.type(selector, value, delay=delay)
                        results.append({"step": i, "action": "type", "selector": selector, "success": True})
                    
                    elif action_type == "press":
                        selector = action.get("selector")
                        key = action.get("key")
                        await page.press(selector, key)
                        results.append({"step": i, "action": "press", "selector": selector, "key": key, "success": True})
                    
                    elif action_type == "wait":
                        timeout = action.get("timeout", 5000)
                        await page.wait_for_timeout(timeout)
                        results.append({"step": i, "action": "wait", "timeout": timeout, "success": True})
                    
                    elif action_type == "wait_for_selector":
                        selector = action.get("selector")
                        state = action.get("state", "visible")
                        timeout = action.get("timeout", 10000)
                        await page.wait_for_selector(selector, state=state, timeout=timeout)
                        results.append({"step": i, "action": "wait_for_selector", "selector": selector, "success": True})
                    
                    elif action_type == "evaluate":
                        script = action.get("script")
                        result = await page.evaluate(script)
                        results.append({"step": i, "action": "evaluate", "result": result, "success": True})
                    
                    elif action_type == "screenshot":
                        path = action.get("path")
                        full_page = action.get("full_page", False)
                        if path:
                            await page.screenshot(path=path, full_page=full_page)
                            results.append({"step": i, "action": "screenshot", "path": path, "success": True})
                        else:
                            import base64
                            screenshot = await page.screenshot(full_page=full_page)
                            b64 = base64.b64encode(screenshot).decode()
                            results.append({"step": i, "action": "screenshot", "screenshot_b64": b64, "success": True})
                    
                    elif action_type == "pdf":
                        path = action.get("path")
                        if path:
                            await page.pdf(path=path)
                            results.append({"step": i, "action": "pdf", "path": path, "success": True})
                    
                    elif action_type == "wait_for_navigation":
                        await page.wait_for_load_state("networkidle")
                        results.append({"step": i, "action": "wait_for_navigation", "success": True})
                    
                    else:
                        results.append({"step": i, "action": action_type, "success": False, "error": f"Unknown action type: {action_type}"})
                
                except Exception as exc:
                    results.append({"step": i, "action": action_type, "success": False, "error": str(exc)})
            
            await browser.close()
            
            success_count = sum(1 for r in results if r.get("success"))
            msg = f"Automation completed: {success_count}/{len(results)} steps succeeded"
            
            return ToolResult(
                success=success_count == len(results),
                message=msg,
                data={"results": results},
            )
            
    except Exception as exc:
        logger.warning("browser_automate failed: %s", exc)
        return ToolResult(success=False, message=f"Browser automation failed: {exc}")


@tool(
    name="browser_extract_structured",
    description=(
        "Extracts structured data from a web page using CSS selectors. "
        "Provide a URL and a mapping of field names to CSS selectors. "
        "Returns JSON with extracted data. Supports single elements or lists."
    ),
)
async def browser_extract_structured(
    url: str,
    fields: Dict[str, str],
    list_selector: Optional[str] = None,
    wait_for: str = "networkidle"
) -> ToolResult:
    if not PLAYWRIGHT_AVAILABLE:
        return ToolResult(success=False, message="Playwright not available.")
    
    if not fields:
        return ToolResult(success=False, message="No fields specified.")
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.goto(url, wait_until=wait_for, timeout=30000)
            
            result = {}
            
            if list_selector:
                # Extract list of objects
                elements = await page.query_selector_all(list_selector)
                items = []
                for el in elements[:50]:  # Limit to 50 items
                    item = {}
                    for field_name, selector in fields.items():
                        try:
                            if selector.startswith("@"):
                                # Attribute extraction
                                attr = selector[1:]
                                value = await el.get_attribute(attr)
                            else:
                                child = await el.query_selector(selector)
                                value = await child.inner_text() if child else None
                            item[field_name] = value
                        except Exception:
                            item[field_name] = None
                    items.append(item)
                result["items"] = items
            else:
                # Extract single object
                for field_name, selector in fields.items():
                    try:
                        if selector.startswith("@"):
                            # Get attribute from body or root element
                            element = await page.query_selector("body")
                            value = await element.get_attribute(selector[1:])
                        else:
                            element = await page.query_selector(selector)
                            value = await element.inner_text() if element else None
                        result[field_name] = value
                    except Exception:
                        result[field_name] = None
            
            await browser.close()
            
            return ToolResult(
                success=True,
                message=f"Extracted {len(fields)} fields from {url}",
                data=result,
            )
            
    except Exception as exc:
        logger.warning("browser_extract_structured failed: %s", exc)
        return ToolResult(success=False, message=f"Structured extraction failed: {exc}")