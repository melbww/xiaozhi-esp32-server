import json
import httpx
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

# 定义基础的函数描述模板
SEARCH_FROM_RAGFLOW_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "search_from_ragflow",
        "description": "Query information from the knowledge base",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "The question to query"}},
            "required": ["question"],
        },
    },
}


@register_function(
    "search_from_ragflow", SEARCH_FROM_RAGFLOW_FUNCTION_DESC, ToolType.SYSTEM_CTL
)
async def search_from_ragflow(conn: "ConnectionHandler", question=None):
    # 确保字符串参数正确处理编码
    if question and isinstance(question, str):
        # 确保问题参数是UTF-8编码的字符串
        pass
    else:
        question = str(question) if question is not None else ""

    ragflow_config = conn.config.get("plugins", {}).get("search_from_ragflow", {})
    base_url = ragflow_config.get("base_url", "")
    api_key = ragflow_config.get("api_key", "")
    dataset_ids = ragflow_config.get("dataset_ids", [])

    url = base_url + "/api/v1/retrieval"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 确保payload中的字符串都是UTF-8编码
    payload = {"question": question, "dataset_ids": dataset_ids}

    try:
        # 使用ensure_ascii=False确保JSON序列化时正确处理中文
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0), verify=False) as client:
            response = await client.post(url, json=payload, headers=headers)

        # 显式设置响应的编码为utf-8
        response.encoding = "utf-8"

        response.raise_for_status()

        # 先获取文本内容，然后手动处理JSON解码
        response_text = response.text

        result = json.loads(response_text)

        if result.get("code") != 0:
            error_detail = result.get("error", {}).get("detail", "unknown error")
            error_message = result.get("error", {}).get("message", "")
            error_code = result.get("code", "")

            # 安全地记录错误信息
            logger.bind(tag=TAG).error(
                f"RAGFlow API调用失败，响应码：{error_code}，错误详情：{error_detail}，完整响应：{result}"
            )

            # 构建详细的错误响应
            error_response = f"The RAG interface returned an error (error code: {error_code})"

            if error_message:
                error_response += f": {error_message}"
            if error_detail:
                error_response += f"\nDetails: {error_detail}"

            return ActionResponse(Action.RESPONSE, None, error_response)

        chunks = result.get("data", {}).get("chunks", [])
        contents = []
        for chunk in chunks:
            content = chunk.get("content", "")
            if content:
                # 安全地处理内容字符串
                if isinstance(content, str):
                    contents.append(content)
                elif isinstance(content, bytes):
                    contents.append(content.decode("utf-8", errors="replace"))
                else:
                    contents.append(str(content))

        if contents:
            # 组织知识库内容为引用模式
            context_text = f"# The knowledge base returned the following for the question [{question}]\n"
            context_text += "```\n\n\n".join(contents[:5])
            context_text += "\n```"
        else:
            context_text = "Based on the knowledge base results, there is no relevant information."
        return ActionResponse(Action.REQLLM, context_text, None)

    except httpx.TimeoutException as e:
        error_response = "The RAG interface request timed out"
        error_response += "\nPossible cause: the RAGflow service is responding slowly or there is network latency"
        error_response += "\nSolution: retry later or check the performance of the RAGflow service"
        return ActionResponse(Action.RESPONSE, None, error_response)

    except httpx.HTTPStatusError as e:
        if hasattr(e.response, "status_code"):
            status_code = e.response.status_code
            error_response = f"RAG interface HTTP error (status code: {status_code})"
            try:
                error_detail = e.response.json().get("error", {}).get("message", "")
                if error_detail:
                    error_response += f"\nError details: {error_detail}"
            except:
                pass
        else:
            error_response = f"RAG interface HTTP exception: {str(e)}"
        return ActionResponse(Action.RESPONSE, None, error_response)

    except httpx.HTTPError as e:
        error_response = "Unable to connect to the RAG interface"
        error_response += "\nPossible cause: the RAGflow service address is wrong or the service is not running"
        error_response += "\nSolution: check the RAGflow service address configuration and service status"
        return ActionResponse(Action.RESPONSE, None, error_response)

    except Exception as e:
        # 其他异常
        error_type = type(e).__name__
        logger.bind(tag=TAG).error(
            f"RAGflow处理异常，异常类型：{error_type}，详情：{str(e)}"
        )

        # 提供详细的错误信息
        error_response = f"RAG interface processing exception ({error_type}): {str(e)}"
        return ActionResponse(Action.RESPONSE, None, error_response)
