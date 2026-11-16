from datetime import datetime
import cnlunar
from plugins_func.register import register_function, ToolType, ActionResponse, Action

get_lunar_function_desc = {
    "type": "function",
    "function": {
        "name": "get_lunar",
        "description": (
            "Provides lunar (Chinese calendar) and almanac information for a specific date. "
            "The user may specify what to query, such as: lunar date, heavenly stems and earthly branches, solar terms, Chinese zodiac, star sign, eight characters (BaZi), auspicious/inauspicious activities, etc. "
            "If no query content is specified, the sexagenary year and lunar date are queried by default. "
            "For basic queries such as 'what is today's lunar date', use the information in the context directly and do not call this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date to query, in YYYY-MM-DD format, e.g. 2024-01-01. If not provided, the current date is used",
                },
                "query": {
                    "type": "string",
                    "description": "What to query, e.g. lunar date, heavenly stems and earthly branches, festivals, solar terms, Chinese zodiac, star sign, eight characters (BaZi), auspicious/inauspicious activities, etc.",
                },
            },
            "required": [],
        },
    },
}


@register_function("get_lunar", get_lunar_function_desc, ToolType.WAIT)
def get_lunar(date=None, query=None):
    """
    用于获取当前的阴历/农历，和天干地支、节气、生肖、星座、八字、宜忌等黄历信息
    """
    from core.utils.cache.manager import cache_manager, CacheType

    # 如果提供了日期参数，则使用指定日期；否则使用当前日期
    if date:
        try:
            now = datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return ActionResponse(
                Action.REQLLM,
                f"Invalid date format. Please use YYYY-MM-DD, e.g. 2024-01-01",
                None,
            )
    else:
        now = datetime.now()

    current_date = now.strftime("%Y-%m-%d")

    # 如果 query 为 None，则使用默认文本
    if query is None:
        query = "the sexagenary year and lunar date by default"

    # 尝试从缓存获取农历信息
    lunar_cache_key = f"lunar_info_{current_date}"
    cached_lunar_info = cache_manager.get(CacheType.LUNAR, lunar_cache_key)
    if cached_lunar_info:
        return ActionResponse(Action.REQLLM, cached_lunar_info, None)

    response_text = f"Based on the information below, answer the user's query and provide information related to {query}:\n"

    lunar = cnlunar.Lunar(now, godType="8char")
    response_text += (
        "Lunar information:\n"
        "%s%s%s (lunar)\n" % (lunar.lunarYearCn, lunar.lunarMonthCn[:-1], lunar.lunarDayCn)
        + "Stems and branches: %s year, %s month, %s day\n" % (lunar.year8Char, lunar.month8Char, lunar.day8Char)
        + "Chinese zodiac: Year of the %s\n" % (lunar.chineseYearZodiac)
        + "BaZi: %s\n"
        % (
            " ".join(
                [lunar.year8Char, lunar.month8Char, lunar.day8Char, lunar.twohour8Char]
            )
        )
        + "Today's festivals: %s\n"
        % (
            ",".join(
                filter(
                    None,
                    (
                        lunar.get_legalHolidays(),
                        lunar.get_otherHolidays(),
                        lunar.get_otherLunarHolidays(),
                    ),
                )
            )
        )
        + "Today's solar term: %s\n" % (lunar.todaySolarTerms)
        + "Next solar term: %s %s-%s-%s\n"
        % (
            lunar.nextSolarTerm,
            lunar.nextSolarTermYear,
            lunar.nextSolarTermDate[0],
            lunar.nextSolarTermDate[1],
        )
        + "Solar terms this year: %s\n"
        % (
            ", ".join(
                [
                    f"{term}({date[0]}-{date[1]})"
                    for term, date in lunar.thisYearSolarTermsDic.items()
                ]
            )
        )
        + "Zodiac clash: %s\n" % (lunar.chineseZodiacClash)
        + "Star sign: %s\n" % (lunar.starZodiac)
        + "NaYin: %s\n" % lunar.get_nayin()
        + "Peng Zu taboos: %s\n" % (lunar.get_pengTaboo(delimit=", "))
        + "Day officer: %s on duty\n" % lunar.get_today12DayOfficer()[0]
        + "Duty deity: %s(%s)\n"
        % (lunar.get_today12DayOfficer()[1], lunar.get_today12DayOfficer()[2])
        + "28 Lunar Mansions: %s\n" % lunar.get_the28Stars()
        + "Lucky directions: %s\n" % " ".join(lunar.get_luckyGodsDirection())
        + "Today's fetal deity: %s\n" % lunar.get_fetalGod()
        + "Auspicious: %s\n" % ", ".join(lunar.goodThing[:10])
        + "Inauspicious: %s\n" % ", ".join(lunar.badThing[:10])
        + "(Returns the sexagenary year and lunar date by default; return today's auspicious/inauspicious activities only when asked for them)"
    )

    # 缓存农历信息
    cache_manager.set(CacheType.LUNAR, lunar_cache_key, response_text)

    return ActionResponse(Action.REQLLM, response_text, None)
