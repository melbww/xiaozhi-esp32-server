import random
import httpx
from io import BytesIO
from urllib.parse import quote, urlsplit, urlunsplit, parse_qsl
from markitdown import MarkItDown, StreamInfo
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
logger = setup_logging()

CHANNEL_MAP = {
    "V2EX": "v2ex-share",
    "知乎": "zhihu",
    "微博": "weibo",
    "联合早报": "zaobao",
    "酷安": "coolapk",
    "MKTNews": "mktnews-flash",
    "华尔街见闻": "wallstreetcn-quick",
    "36氪": "36kr-quick",
    "抖音": "douyin",
    "虎扑": "hupu",
    "百度贴吧": "tieba",
    "今日头条": "toutiao",
    "IT之家": "ithome",
    "澎湃新闻": "thepaper",
    "卫星通讯社": "sputniknewscn",
    "参考消息": "cankaoxiaoxi",
    "远景论坛": "pcbeta-windows11",
    "财联社": "cls-depth",
    "雪球": "xueqiu-hotstock",
    "格隆汇": "gelonghui",
    "法布财经": "fastbull-express",
    "Solidot": "solidot",
    "Hacker News": "hackernews",
    "Product Hunt": "producthunt",
    "Github": "github-trending-today",
    "哔哩哔哩": "bilibili-hot-search",
    "快手": "kuaishou",
    "靠谱新闻": "kaopu",
    "金十数据": "jin10",
    "百度热搜": "baidu",
    "牛客": "nowcoder",
    "少数派": "sspai",
    "稀土掘金": "juejin",
    "凤凰网": "ifeng",
    "虫部落": "chongbuluo-latest",
}

# 默认新闻来源字典，当配置中没有指定时使用
DEFAULT_NEWS_SOURCES = "澎湃新闻;百度热搜;财联社"

DEFAULT_NEWS_API_URL = "https://newsnow.busiyi.world/api/s?id="


def _build_news_api_url(source, configured_url=None):
    """拼出新闻接口的请求地址和查询参数。

    配置里带 {source} 占位符就替换占位符；否则把 id 设成新闻源 id，
    这样配置里已经写了 id 时也不会拼出脏串。
    """
    api_url = str(configured_url).strip() if configured_url else DEFAULT_NEWS_API_URL
    if "{source}" in api_url:
        return api_url.replace("{source}", quote(source, safe="")), None
    parts = urlsplit(api_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["id"] = source
    return (
        urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment)),
        query,
    )


def _get_newsnow_config(conn):
    # 从连接配置获取
    plugins = conn.config.get("plugins", {})
    newsnow = plugins.get("get_news_from_newsnow", {})
    sources = newsnow.get("news_sources", "")
    if isinstance(sources, str) and sources.strip():
        return sources
    if isinstance(sources, (list, tuple)):
        return ";".join(str(item).strip() for item in sources if str(item).strip())

    return ""

def get_news_sources_from_config(conn):
    """从配置中获取新闻源字符串"""
    try:
        result = _get_newsnow_config(conn)
        if result:
            logger.bind(tag=TAG).debug(f"使用配置的新闻源: {result}")
            return result

        logger.bind(tag=TAG).debug("未找到新闻源配置，使用默认配置")
        return DEFAULT_NEWS_SOURCES

    except Exception as e:
        logger.bind(tag=TAG).error(f"获取新闻源配置失败: {e}，使用默认配置")
        return DEFAULT_NEWS_SOURCES


# 从默认配置获取可用的新闻源名称（运行时由get_news_sources_from_config动态获取）
example_sources_str = DEFAULT_NEWS_SOURCES.replace(";","、")

GET_NEWS_FROM_NEWSNOW_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "get_news_from_newsnow",
        "description": "Call this when the user asks to view or listen to the news (e.g. 'give me a news item', 'what's in the news today').",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": f"The standard Chinese name of the news source, e.g. {example_sources_str}, etc. Optional parameter; if not provided, the default news source is used",
                },
                "detail": {
                    "type": "boolean",
                    "description": "Whether to fetch the detailed content; defaults to false. If true, fetches the detailed content of the previous news item",
                },
                "lang": {
                    "type": "string",
                    "description": "The language code to reply to the user in, e.g. en_US, ja_JP, zh_CN; defaults to en_US",
                },
            },
            "required": ["lang"],
        },
    },
}


async def fetch_news_from_api(conn: "ConnectionHandler", source="thepaper"):
    """从API获取新闻列表"""
    try:
        news_config = conn.config.get("plugins", {}).get("get_news_from_newsnow", {})
        configured_url = news_config.get("url") if isinstance(news_config, dict) else None
        api_url, request_params = _build_news_api_url(source, configured_url)

        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = await client.get(api_url, params=request_params, headers=headers)

        if response.status_code != 200:
            logger.bind(tag=TAG).error(
                f"获取新闻API失败：HTTP {response.status_code}，source={source}"
            )
            return []
        data = response.json()

        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            logger.bind(tag=TAG).error(f"获取新闻API响应格式错误: {data}")
            return []
        return [item for item in items if isinstance(item, dict) and item.get("title")]

    except Exception as e:
        logger.bind(tag=TAG).error(f"获取新闻API失败: {e}")
        return []


async def fetch_news_detail(url):
    """获取新闻详情页内容并使用MarkItDown清理HTML"""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = await client.get(url, headers=headers)

        # 使用MarkItDown清理HTML内容
        md = MarkItDown(enable_plugins=False)
        result = md.convert_stream(
            BytesIO(response.content),
            stream_info=StreamInfo(
                mimetype="text/html",
                extension=".html",
                charset=response.encoding or "utf-8",
            ),
        )

        # 获取清理后的文本内容
        clean_text = result.text_content

        # 如果清理后的内容为空，返回提示信息
        if not clean_text or len(clean_text.strip()) == 0:
            logger.bind(tag=TAG).warning(f"清理后的新闻内容为空: {url}")
            return "Unable to parse the news detail content; the website structure may be unusual or the content may be restricted."

        return clean_text
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取新闻详情失败: {e}")
        return "Unable to get detailed content"


@register_function(
    "get_news_from_newsnow",
    GET_NEWS_FROM_NEWSNOW_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
async def get_news_from_newsnow(
    conn: "ConnectionHandler",
    source: str = "澎湃新闻",
    detail: bool = False,
    lang: str = "en_US",
):
    """获取新闻并随机选择一条进行播报，或获取上一条新闻的详细内容"""
    try:
        # 获取当前配置的新闻源
        news_sources = get_news_sources_from_config(conn)

        # 如果detail为True，获取上一条新闻的详细内容
        detail = str(detail).lower() == "true"
        if detail:
            if (
                not hasattr(conn, "last_newsnow_link")
                or not conn.last_newsnow_link
                or "url" not in conn.last_newsnow_link
            ):
                return ActionResponse(
                    Action.REQLLM,
                    "Sorry, no recently queried news was found. Please fetch a news item first.",
                    None,
                )

            url = conn.last_newsnow_link.get("url")
            title = conn.last_newsnow_link.get("title", "unknown title")
            source_id = conn.last_newsnow_link.get("source_id", "thepaper")
            source_name = CHANNEL_MAP.get(source_id, "unknown source")

            if not url or url == "#":
                return ActionResponse(
                    Action.REQLLM, "Sorry, there is no available link to fetch the details of this news item.", None
                )

            logger.bind(tag=TAG).debug(
                f"获取新闻详情: {title}, 来源: {source_name}, URL={url}"
            )

            # 获取新闻详情
            detail_content = await fetch_news_detail(url)

            if not detail_content or detail_content == "Unable to get detailed content":
                return ActionResponse(
                    Action.REQLLM,
                    f"Sorry, the details of \"{title}\" could not be fetched; the link may have expired or the website structure may have changed.",
                    None,
                )

            # 构建详情报告
            detail_report = (
                f"Based on the data below, respond to the user's request for news details in {lang}:\n\n"
                f"News title: {title}\n"
                # f"News source: {source_name}\n"
                f"Details: {detail_content}\n\n"
                f"(Summarize the news content above, extract the key points, and deliver it to the user in a natural, fluent way. "
                f"Do not mention that this is a summary; tell it as if recounting a complete news story.)"
            )

            return ActionResponse(Action.REQLLM, detail_report, None)

        # 否则，获取新闻列表并随机选择一条
        # 将中文名称转换为英文ID
        english_source_id = None

        # 检查输入的中文名称是否在配置的新闻源中
        news_sources_list = [name.strip() for name in news_sources.split(";") if name.strip()]
        if source in news_sources_list:
            english_source_id = CHANNEL_MAP.get(source)
        elif not source and news_sources_list:
            source = news_sources_list[0]
            english_source_id = CHANNEL_MAP.get(source)

        # 如果找不到对应的英文ID，使用默认源
        if not english_source_id:
            fallback_source = next(
                (name for name in news_sources_list if CHANNEL_MAP.get(name)),
                "澎湃新闻",
            )
            logger.bind(tag=TAG).warning(
                f"无效的新闻源: {source}，使用配置中的默认源{fallback_source}"
            )
            english_source_id = CHANNEL_MAP[fallback_source]
            source = fallback_source

        logger.bind(tag=TAG).info(f"获取新闻: 新闻源={source}({english_source_id})")

        # 获取新闻列表
        news_items = await fetch_news_from_api(conn, english_source_id)

        if not news_items:
            return ActionResponse(
                Action.REQLLM,
                f"Sorry, no news could be fetched from {source}. Please try again later or try another news source.",
                None,
            )

        # 随机选择一条新闻
        selected_news = random.choice(news_items)
        title = selected_news.get("title", "unknown title")

        # 保存当前新闻链接到连接对象，以便后续查询详情
        if not hasattr(conn, "last_newsnow_link"):
            conn.last_newsnow_link = {}
        conn.last_newsnow_link = {
            "url": selected_news.get("url", "#"),
            "title": title,
            "source_id": english_source_id,
        }

        # 构建新闻报告
        news_report = (
            f"Based on the data below, respond to the user's news query in {lang}:\n\n"
            f"News title: {title}\n"
            # f"News source: {source}\n"
            f"(Announce this news headline to the user in a natural, fluent way, "
            f"and let the user know they can ask for details, which will then be fetched.)"
        )

        return ActionResponse(Action.REQLLM, news_report, None)

    except Exception as e:
        logger.bind(tag=TAG).error(f"获取新闻出错: {e}")
        return ActionResponse(
            Action.REQLLM, "Sorry, an error occurred while fetching the news. Please try again later.", None
        )
