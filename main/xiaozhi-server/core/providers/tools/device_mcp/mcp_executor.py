"""设备端MCP工具执行器"""

from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import Action, ActionResponse
from .mcp_handler import call_mcp_tool


class DeviceMCPExecutor(ToolExecutor):
    """设备端MCP工具执行器"""

    def __init__(self, conn):
        self.conn = conn

    async def execute(
        self, conn: "ConnectionHandler", tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行设备端MCP工具"""
        if not hasattr(conn, "mcp_client") or not conn.mcp_client:
            return ActionResponse(
                action=Action.ERROR,
                response="设备端MCP客户端未初始化",
            )

        if not await conn.mcp_client.is_ready():
            return ActionResponse(
                action=Action.ERROR,
                response="设备端MCP客户端未准备就绪",
            )

        try:
            # 转换参数为JSON字符串
            import json

            args_str = json.dumps(arguments) if arguments else "{}"

            # 调用设备端MCP工具，保留完整的 content，图片不能被丢掉
            result = await call_mcp_tool(
                conn, conn.mcp_client, tool_name, args_str, return_content=True
            )

            if isinstance(result, list):
                text_parts = [
                    part.get("text", "")
                    for part in result
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                images = [
                    {
                        "mimeType": part.get("mimeType") or "image/jpeg",
                        "data": part.get("data"),
                    }
                    for part in result
                    if isinstance(part, dict)
                    and part.get("type") == "image"
                    and part.get("data")
                ]
                text = "\n".join(p for p in text_parts if p)
                if images:
                    response = ActionResponse(
                        action=Action.REQLLM,
                        result=text or "Photo captured.",
                    )
                    # ActionResponse is defined outside core/, so attach the
                    # images dynamically; connection.py reads them with getattr.
                    response.images = images
                    return response
            else:
                text = result

            resultJson = None
            if isinstance(text, str):
                try:
                    resultJson = json.loads(text)
                except Exception as e:
                    pass

            # Legacy vision tool: give the text back to the main LLM instead of
            # speaking it directly (the old Action.RESPONSE path).
            if (
                resultJson is not None
                and isinstance(resultJson, dict)
                and "action" in resultJson
                and "response" in resultJson
            ):
                return ActionResponse(
                    action=Action.REQLLM,
                    result=resultJson.get("response", ""),
                )

            if (
                resultJson is not None
                and isinstance(resultJson, dict)
                and resultJson.get("success") is False
            ):
                return ActionResponse(
                    action=Action.REQLLM,
                    result=resultJson.get("message", text),
                )

            return ActionResponse(
                action=Action.REQLLM,
                result=text if isinstance(text, str) else str(result),
            )

        except ValueError as e:
            return ActionResponse(action=Action.NOTFOUND, response=str(e))
        except Exception as e:
            return ActionResponse(action=Action.ERROR, response=str(e))

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有设备端MCP工具"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return {}

        tools = {}
        mcp_tools = self.conn.mcp_client.get_available_tools()

        for tool in mcp_tools:
            func_def = tool.get("function", {})
            tool_name = func_def.get("name", "")

            if tool_name:
                tools[tool_name] = ToolDefinition(
                    name=tool_name, description=tool, tool_type=ToolType.DEVICE_MCP
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的设备端MCP工具"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return False

        return self.conn.mcp_client.has_tool(tool_name)
