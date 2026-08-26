import webbrowser

from app.tools.base import ToolResult, tool


@tool(
    name="web_search",
    description="Searches the live internet and returns short summaries of the top results. Use for current events, facts, prices, anything you don't know.",
)
def web_search(query: str) -> ToolResult:
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return ToolResult(success=True, message=f"No results found for '{query}'.")
        lines = [
            f"- {r.get('title', '')}: {r.get('body', '')[:220]}"
            for r in results
        ]
        return ToolResult(
            success=True,
            message="Top results:\n" + "\n".join(lines),
            data={"results": results},
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Web search failed: {exc}")


@tool(
    name="open_website",
    description="Opens a URL in the default browser. Provide a full URL including https://.",
)
def open_website(url: str) -> ToolResult:
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    webbrowser.open(url)
    return ToolResult(success=True, message=f"Opened {url} in your browser.")


@tool(
    name="youtube_play",
    description="Searches YouTube for a song or video and plays the first result in the browser.",
)
def youtube_play(query: str) -> ToolResult:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"https://www.youtube.com/results?search_query={query}")
            page.wait_for_selector("ytd-video-renderer a#video-title", timeout=10000)
            href = page.evaluate(
                "document.querySelector('ytd-video-renderer a#video-title').getAttribute('href')"
            )
            browser.close()

        if not href:
            return ToolResult(success=False, message="No video found on YouTube.")
        webbrowser.open(f"https://www.youtube.com{href}")
        return ToolResult(success=True, message=f"Playing '{query}' on YouTube.")
    except Exception as exc:
        try:
            import urllib.parse

            webbrowser.open(
                "https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(query)
            )
            return ToolResult(
                success=True,
                message=f"Opened YouTube search results for '{query}' in your browser.",
            )
        except Exception:
            return ToolResult(success=False, message=f"YouTube playback failed: {exc}")
