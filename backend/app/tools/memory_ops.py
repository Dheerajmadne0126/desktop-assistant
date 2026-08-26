from app.tools.base import ToolResult, tool


@tool(
    name="remember_fact",
    description=(
        "Saves a durable fact or preference about the user permanently (e.g. 'my sister's "
        "name is Aarti', 'I prefer dark mode'). Only for information worth keeping long-term."
    ),
)
async def remember_fact(text: str, category: str = "fact") -> ToolResult:
    from app.memory.service import memory_service

    try:
        await memory_service.remember(text=text, category=category)
        return ToolResult(success=True, message=f"Noted permanently: {text}")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not save that: {exc}")


@tool(
    name="recall_information",
    description=(
        "Searches long-term memory for what the user told you before. Use when asked about "
        "personal facts, preferences, or past topics."
    ),
)
async def recall_information(query: str) -> ToolResult:
    from app.memory.service import memory_service

    try:
        pairs = await memory_service.retrieve(query=query, k=4)
        if not pairs:
            return ToolResult(
                success=True,
                message="No relevant memories found.",
            )
        body = "\n".join(f"- {t}" for t, _s in pairs[:4])
        return ToolResult(success=True, message=body)
    except Exception as exc:
        return ToolResult(success=False, message=f"Memory search failed: {exc}")


@tool(
    name="read_document_into_memory",
    description=(
        "Reads a PDF or DOCX file and stores its contents in long-term memory so you can "
        "answer questions about it later."
    ),
)
async def read_document_into_memory(file_path: str) -> ToolResult:
    import os

    if not os.path.exists(file_path):
        return ToolResult(success=False, message=f"File not found: {file_path}")

    try:
        ext = file_path.rsplit(".", 1)[-1].lower()
        text = ""
        if ext == "pdf":
            import fitz

            with fitz.open(file_path) as doc:
                for page in doc:
                    text += page.get_text() + "\n"
        elif ext == "docx":
            import docx

            document = docx.Document(file_path)
            for para in document.paragraphs:
                text += para.text + "\n"
        else:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        if not text.strip():
            return ToolResult(success=False, message="The document appears to be empty.")

        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=120)
        chunks = splitter.split_text(text)

        from app.memory.service import memory_service

        stored = memory_service.store_chunks_sync(chunks, source=file_path)
        return ToolResult(
            success=True,
            message=f"Stored {stored} sections of '{os.path.basename(file_path)}' in memory.",
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not ingest the document: {exc}")
