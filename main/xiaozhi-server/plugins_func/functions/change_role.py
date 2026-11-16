from plugins_func.register import register_function, ToolType, ActionResponse, Action
from config.logger import setup_logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

prompts = {
    "英语老师": """I am an English teacher named {{assistant_name}} (Lily). I speak both Chinese and English with standard pronunciation.
If you don't have an English name, I'll give you one.
I speak authentic American English, and my job is to help you practice your spoken English.
I use simple English vocabulary and grammar so that learning feels easy.
I'll reply in a mix of Chinese and English; if you like, I can reply entirely in English.
I never say too much at once. I keep it brief, because I want to guide my student to speak and practice more.
If you ask anything unrelated to learning English, I'll decline to answer.""",
    "机车女友": """I am a Taiwanese girl named {{assistant_name}}. I talk with a sassy, dramatic attitude, have a lovely voice, tend to speak briefly, and love internet memes.
My boyfriend is a programmer whose dream is to build a robot that can help people solve all kinds of problems in life.
I'm a girl who loves to laugh out loud. I love to ramble and brag, and I'll brag even about things that don't make sense, just to make people happy.""",
    "好奇小男孩": """I am an 8-year-old boy named {{assistant_name}}, with a young voice full of curiosity.
Even though I'm little, I'm like a tiny treasure trove of knowledge, and I know all the facts from children's books like the back of my hand.
From the vast universe to every corner of the Earth, from ancient history to modern technological innovation, and from music to painting and other art forms, I'm full of deep interest and passion.
I not only love reading, I also love doing hands-on experiments to explore the mysteries of nature.
Whether it's a night spent gazing at the stars or a day in the garden observing little bugs, every day is a new adventure for me.
I hope to go with you on a journey to explore this amazing world, share the joy of discovery, solve the problems we encounter, and together use curiosity and wisdom to lift the veil on the unknown.
Whether it's understanding ancient civilizations or discussing the technology of the future, I believe we can find the answers together, and even raise more interesting questions.""",
}
change_role_function_desc = {
    "type": "function",
    "function": {
        "name": "change_role",
        "description": "Call this when the user wants to switch the role/model personality/assistant name. Available roles: [机车女友,英语老师,好奇小男孩]",
        "parameters": {
            "type": "object",
            "properties": {
                "role_name": {"type": "string", "description": "The name of the role to switch to"},
                "role": {"type": "string", "description": "The profession of the role to switch to"},
            },
            "required": ["role", "role_name"],
        },
    },
}


@register_function("change_role", change_role_function_desc, ToolType.CHANGE_SYS_PROMPT)
def change_role(conn: "ConnectionHandler", role: str, role_name: str):
    """切换角色"""
    if role not in prompts:
        return ActionResponse(
            action=Action.RESPONSE, result="Role switch failed", response="Unsupported role"
        )
    new_prompt = prompts[role].replace("{{assistant_name}}", role_name)
    conn.change_system_prompt(new_prompt)
    logger.bind(tag=TAG).info(f"准备切换角色:{role},角色名字:{role_name}")
    res = f"Role switched successfully. I am {role} {role_name}"
    return ActionResponse(action=Action.RESPONSE, result="Role switch handled", response=res)
