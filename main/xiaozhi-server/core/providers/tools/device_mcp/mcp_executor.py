"""设备端MCP工具执行器"""

import base64
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import Action, ActionResponse
from .mcp_handler import call_mcp_tool

# Container cwd is /opt/xiaozhi-esp32-server; tmp/ is bind-mounted to
# my_explorations/server/deploy/logs, which the log viewer serves as /photos/.
PHOTO_ROOT = Path(os.environ.get("XIAOZHI_PHOTO_DIR", "tmp/photos"))


def _save_photo_parts(conn, images):
    """Persist received JPEGs and return /photos/... URLs for the log viewer."""
    urls = []
    for image in images:
        data = image.get("data")
        if not data:
            continue
        mime = image.get("mimeType") or "image/jpeg"
        ext = "jpg" if "jpeg" in mime else (mime.split("/")[-1] or "bin")
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        name = (
            f"{time.strftime('%H-%M-%S', time.localtime(now))}-"
            f"{uuid.uuid4().hex[:8]}.{ext}"
        )
        target = PHOTO_ROOT / day / name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(data))
        except Exception as exc:
            logger = getattr(conn, "logger", None)
            if logger is not None:
                logger.bind(tag=__name__).warning(f"PHOTO save failed: {exc}")
            continue
        url = f"/photos/{day}/{name}"
        urls.append(url)
        logger = getattr(conn, "logger", None)
        if logger is not None:
            logger.bind(tag=__name__).info(f"PHOTO {url}")
    return urls


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
                    # Save the exact photo for the log viewer and emit a short
                    # /photos/... line instead of dumping base64 into the log.
                    response.photo_urls = _save_photo_parts(conn, images)
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
