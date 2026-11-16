import random
import httpx
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
logger = setup_logging()

GET_NEWS_FROM_CHINANEWS_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "get_news_from_chinanews",
        "description": (
            "Call this when the user asks to view or listen to the news (e.g. 'give me a news item', 'what's in the news today'). "
            "The user may specify a news type, such as social news, tech news, international news, etc. "
            "If none is specified, social news is broadcast by default."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "News category, e.g. society, technology, world. Optional parameter; if not provided, the default category is used",
                },
                "detail": {
                    "type": "boolean",
                    "description": "Whether to fetch the detailed content; defaults to false. If true, fetches the detailed content of the previous news item",
                },
                "lang": {
                    "type": "string",
                    "description": "The language code to reply to the user in, e.g. zh_CN/zh_HK/en_US/ja_JP; defaults to zh_CN",
                },
            },
            "required": ["lang"],
        },
    },
}


async def fetch_news_from_rss(rss_url):
    """从RSS源获取新闻列表"""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
            response = await client.get(rss_url)

        # 解析XML
        root = ET.fromstring(response.content)

        # 查找所有item元素（新闻条目）
        news_items = []
        for item in root.findall(".//item"):
            title = (
                item.find("title").text if item.find("title") is not None else "untitled"
            )
            link = item.find("link").text if item.find("link") is not None else "#"
            description = (
                item.find("description").text
                if item.find("description") is not None
                else "no description"
            )
            pubDate = (
                item.find("pubDate").text
                if item.find("pubDate") is not None
                else "unknown time"
            )

            news_items.append(
                {
                    "title": title,
                    "link": link,
                    "description": description,
                    "pubDate": pubDate,
                }
            )

        return news_items
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取RSS新闻失败: {e}")
        return []


async def fetch_news_detail(url):
    """获取新闻详情页内容并总结"""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            response = await client.get(url)

        soup = BeautifulSoup(response.content, "html.parser")

        # 尝试提取正文内容 (这里的选择器需要根据实际网站结构调整)
        content_div = soup.select_one(
            ".content_desc, .content, article, .article-content"
        )
        if content_div:
            paragraphs = content_div.find_all("p")
            content = "\n".join(
                [p.get_text().strip() for p in paragraphs if p.get_text().strip()]
            )
            return content
        else:
            # 如果找不到特定的内容区域，尝试获取所有段落
            paragraphs = soup.find_all("p")
            content = "\n".join(
                [p.get_text().strip() for p in paragraphs if p.get_text().strip()]
            )
            return content[:2000]  # 限制长度
    except Exception as e:
        logger.bind(tag=TAG).error(f"获取新闻详情失败: {e}")
        return "Unable to get detailed content"


def map_category(category_text):
    """将用户输入的中文类别映射到配置文件中的类别键"""
    if not category_text:
        return None

    # 类别映射字典，目前支持社会、国际、财经新闻，如需更多类型，参见配置文件
    category_map = {
        # 社会新闻
        "社会": "society_rss_url",
        "社会新闻": "society_rss_url",
        # 国际新闻
        "国际": "world_rss_url",
        "国际新闻": "world_rss_url",
        # 财经新闻
        "财经": "finance_rss_url",
        "财经新闻": "finance_rss_url",
        "金融": "finance_rss_url",
        "经济": "finance_rss_url",
    }

    # 转换为小写并去除空格
    normalized_category = category_text.lower().strip()

    # 返回映射结果，如果没有匹配项则返回原始输入
    return category_map.get(normalized_category, category_text)


@register_function(
    "get_news_from_chinanews",
    GET_NEWS_FROM_CHINANEWS_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
async def get_news_from_chinanews(
    conn: "ConnectionHandler",
    category: str = None,
    detail: bool = False,
    lang: str = "zh_CN",
):
    """获取新闻并随机选择一条进行播报，或获取上一条新闻的详细内容"""
    try:
        # 如果detail为True，获取上一条新闻的详细内容
        if detail:
            if (
                not hasattr(conn, "last_news_link")
                or not conn.last_news_link
                or "link" not in conn.last_news_link
            ):
                return ActionResponse(
                    Action.REQLLM,
                    "Sorry, no recently queried news was found. Please fetch a news item first.",
                    None,
                )

            link = conn.last_news_link.get("link")
            title = conn.last_news_link.get("title", "unknown title")

            if link == "#":
                return ActionResponse(
                    Action.REQLLM, "Sorry, there is no available link to fetch the details of this news item.", None
                )

            logger.bind(tag=TAG).debug(f"获取新闻详情: {title}, URL={link}")

            # 获取新闻详情
            detail_content = await fetch_news_detail(link)

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
                f"Details: {detail_content}\n\n"
                f"(Summarize the news content above, extract the key points, and deliver it to the user in a natural, fluent way. "
                f"Do not mention that this is a summary; tell it as if recounting a complete news story.)"
            )

            return ActionResponse(Action.REQLLM, detail_report, None)

        # 否则，获取新闻列表并随机选择一条
        # 从配置中获取RSS URL
        rss_config = conn.config.get("plugins", {}).get("get_news_from_chinanews", {})
        default_rss_url = rss_config.get(
            "default_rss_url", "https://www.chinanews.com.cn/rss/society.xml"
        )

        # 将用户输入的类别映射到配置中的类别键
        mapped_category = map_category(category)

        # 如果提供了类别，尝试从配置中获取对应的URL
        rss_url = default_rss_url
        if mapped_category and mapped_category in rss_config:
            rss_url = rss_config[mapped_category]

        logger.bind(tag=TAG).info(
            f"获取新闻: 原始类别={category}, 映射类别={mapped_category}, URL={rss_url}"
        )

        # 获取新闻列表
        news_items = await fetch_news_from_rss(rss_url)

        if not news_items:
            return ActionResponse(
                Action.REQLLM, "Sorry, no news could be fetched. Please try again later.", None
            )

        # 随机选择一条新闻
        selected_news = random.choice(news_items)

        # 保存当前新闻链接到连接对象，以便后续查询详情
        if not hasattr(conn, "last_news_link"):
            conn.last_news_link = {}
        conn.last_news_link = {
            "link": selected_news.get("link", "#"),
            "title": selected_news.get("title", "unknown title"),
        }

        # 构建新闻报告
        news_report = (
            f"Based on the data below, respond to the user's news query in {lang}:\n\n"
            f"News title: {selected_news['title']}\n"
            f"Published at: {selected_news['pubDate']}\n"
            f"News content: {selected_news['description']}\n"
            f"(Announce this news to the user in a natural, fluent way. Summarizing the content a little is fine, "
            f"but just read the news directly without extra padding. "
            f"If the user asks for more details, tell them they can say 'please tell me more about this news' to get more content.)"
        )

        return ActionResponse(Action.REQLLM, news_report, None)

    except Exception as e:
        logger.bind(tag=TAG).error(f"获取新闻出错: {e}")
        return ActionResponse(
            Action.REQLLM, "Sorry, an error occurred while fetching the news. Please try again later.", None
        )
