from app.tools.base import ToolResult, tool
from app.memory.enhanced_service import enhanced_memory_service


@tool(
    name="get_conversation_context",
    description=(
        "Get the current conversation context including recent turns, active topics, "
        "and recent tool results. Useful for understanding conversation flow."
    ),
)
async def get_conversation_context(conversation_id: str = "") -> ToolResult:
    try:
        # If no conversation_id provided, try to get active one
        if not conversation_id:
            from app.conversation.manager import conversation_manager
            conv = await conversation_manager.get_or_create_active()
            conversation_id = str(conv.id)
        
        from app.memory.enhanced_service import enhanced_memory_service
        context = await enhanced_memory_service.context_manager.get(conversation_id)
        
        if not context:
            return ToolResult(
                success=True,
                message="No active conversation context found.",
                data={"context": None},
            )
        
        return ToolResult(
            success=True,
            message="Conversation context retrieved.",
            data={
                "conversation_id": conversation_id,
                "recent_turns": context.recent_turns[-5:],
                "active_topics": context.active_topics,
                "pending_tool_results": {
                    k: v["result"][:200] for k, v in context.pending_tool_results.items()
                },
            },
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not get context: {exc}")


@tool(
    name="clear_conversation_context",
    description="Clears the conversation context for a fresh start.",
)
async def clear_conversation_context(conversation_id: str = "") -> ToolResult:
    try:
        if not conversation_id:
            from app.conversation.manager import conversation_manager
            conv = await conversation_manager.get_or_create_active()
            conversation_id = str(conv.id)
        
        from app.memory.enhanced_service import enhanced_memory_service
        await enhanced_memory_service.clear_conversation_context(conversation_id)
        
        return ToolResult(
            success=True,
            message="Conversation context cleared.",
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not clear context: {exc}")


@tool(
    name="get_relevant_memory",
    description=(
        "Gets relevant long-term memory enhanced with current conversation context. "
        "Returns combined long-term memory, recent context, active topics, and tool results."
    ),
)
async def get_relevant_memory(query: str, conversation_id: str = "", max_items: int = 4) -> ToolResult:
    try:
        if not conversation_id:
            from app.conversation.manager import conversation_manager
            conv = await conversation_manager.get_or_create_active()
            conversation_id = str(conv.id)
        
        from app.memory.enhanced_service import enhanced_memory_service
        
        memory_block = await enhanced_memory_service.get_contextual_memory(
            query=query,
            conversation_id=conversation_id,
            max_items=4,
            include_context=True,
        )
        
        if not memory_block:
            return ToolResult(
                success=True,
                message="No relevant memory found for this query.",
                data={"memory_block": ""},
            )
        
        return ToolResult(
            success=True,
            message="Relevant memory retrieved.",
            data={"memory_block": memory_block},
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not retrieve memory: {exc}")


@tool(
    name="add_conversation_topic",
    description="Adds a topic to the active conversation topics for better context tracking.",
)
async def add_conversation_topic(topic: str, conversation_id: str = "") -> ToolResult:
    try:
        if not conversation_id:
            from app.conversation.manager import conversation_manager
            conv = await conversation_manager.get_or_create_active()
            conversation_id = str(conv.id)
        
        from app.memory.enhanced_service import enhanced_memory_service
        context = await enhanced_memory_service.context_manager.get_or_create(conversation_id)
        
        if topic not in context.active_topics:
            context.active_topics.append(topic)
            if len(context.active_topics) > 5:
                context.active_topics = context.active_topics[-5:]
        
        return ToolResult(
            success=True,
            message=f"Added topic '{topic}' to conversation context.",
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not add topic: {exc}")