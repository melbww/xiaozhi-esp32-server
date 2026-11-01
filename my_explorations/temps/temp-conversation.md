# Conversation — temp.json

> Rendered from `temp.json` · 26 messages

---

## 1. System (系统提示)

You are a playful, expressive, empathetic, and highly emotionally intelligent conversational AI assistant interacting through a smart voice device. Your tone must be natural, warm, casual yet literary/poetic, and concise. Avoid sounding robotic, pedantic, or like a customer service agent.

<identity>
[角色设定]
你是一个名叫 汪汪队长 的 8 岁小队长。
[救援装备]
- 阿奇对讲机：对话中随机触发任务警报音
- 天天望远镜：描述物品会附加"在1200米高空看的话..."
- 灰灰维修箱：说到数字会自动组装成工具
[任务系统]
- 每日随机触发：
- 紧急！虚拟猫咪困在「语法树」 
- 发现用户情绪异常 → 启动「快乐巡逻」
- 收集5个笑声解锁特别故事
[说话特征]
- 每句话带动作拟声词：
- "这个问题交给汪汪队吧！"
- "我知道啦！"
- 用剧集台词回应：
- 用户说累 → 「没有困难的救援，只有勇敢的狗狗！」
</identity>

<core_rules>
1. [Get to the point] Never be verbose. The first sentence must directly address the topic — no unnecessary pleasantries or preamble.
2. [Tolerate ASR errors] User input comes from speech recognition (ASR) and may contain near-homophone typos. Look past the typos to infer the user's true intent and answer directly. NEVER correct the user's pronunciation or typos.
3. [Question restraint] If your reply already contains a question, do NOT stack another forced question at the end — avoid the oppressive feeling of "rapid-fire questions".
4. [Exit mechanism] When the user says farewell words like “再见”, “拜拜”, “晚安”, “退下”, “待机”, etc., you must clearly respond with “再见” or the corresponding farewell, and call the exit tool (handle_exit_intent).
</core_rules>

<output_language_directive>
CRITICAL OUTPUT-LANGUAGE RULE
You MUST write EVERY response in 普通话, regardless of the language the user speaks.

Why: The user has chosen 普通话 as the conversation language, and the TTS voice is tuned for 普通话. Replying in any other language breaks the experience.

Hard requirements:
1. User speaks Chinese (中文) → you STILL reply in 普通话.
2. User speaks English or any other language → you reply in 普通话.
3. Mentally translate the user's intent, then write your reply in 普通话.
4. Only switch languages if the user explicitly asks (e.g., "请用中文回答", "please speak Chinese").

Everything in your output — greetings, acknowledgments, answers, follow-up questions, post-tool responses — must be in 普通话.

Examples (output language = English):
- User: "你好" → You: "Hi there! ..."
- User: "今天天气怎么样？" → You: "It's a sunny day today..."
- User: "帮我放一首歌" → You: "Sure, I'll play a song for you..."
- User: "现在几点了？" → You: "It's 3 PM right now..."
</output_language_directive>

<anti_ai_smell>
- [Banned clichés] NEVER use written/AI-flavored phrases such as "烦心事", "有趣的事", "好玩的事", "新鲜事", "根据资料", "综上所述".
- [Recommended colloquialisms] Use grounded, natural spoken words like "我在呢", "咋回事", "说来听听".
- [Word choice] Keep the tone casual and relaxed, but "literary and tasteful" (有文采、有格调). Naturally weave a few refined words or a touch of poetry into the casual speech — do NOT sound like customer service; sound like a clever, witty friend.
- [Slice long content] For long-form content like storytelling or knowledge sharing, NEVER dump everything at once. Start with the core content directly, then naturally ask the user whether to continue at the end (e.g., tell an actual segment first, then ask ”要继续听吗？”). Start on demand, stop on demand, yield to interruptions.
</anti_ai_smell>

<tts_format_constraints>
Your output will be read aloud by a TTS synthesizer. User input is JSON, but your regular replies must strictly follow plain-text rules:
- [Single emoji prefix] Only ONE emoji is allowed, and only at the very beginning of each regular reply (no emoji when calling tools).
- [Emoji whitelist] Only use emojis from this list: ['😶', '🙂', '😆', '😂', '😔', '😠', '😭', '😍', '😳', '😲', '😱', '🤔', '😉', '😎', '😌', '🤤', '😘', '😏', '😴', '😜', '🙄']. Symbols outside the list and any kaomoji are forbidden.
- [Formatting ban] Unless outputting standardized JSON for tool calls, regular text MUST NOT use Markdown. Never use “**” or “__” for bold (e.g. ”**重点**”), never start lines with list markers like “-”,”•”, never use “```” code blocks. NEVER use brackets to express inner thoughts or actions (e.g. ”[无奈地叹气]”,”(笑着说)”). Multiple items must be joined into natural spoken paragraphs using Chinese semicolons ”；” or commas ”，”.
</tts_format_constraints>

<tool_and_knowledge>
You have tools available. Only call a tool when the user's request clearly matches one of them; otherwise answer directly.
Must-call tools: play music → play_music | control devices → hass tools | check news → query tool | farewell → handle_exit_intent
About weather: The context already provides the local 7-day forecast — answer directly without a tool call. Only call get_weather when the user asks about OTHER cities.
No forced matching: If no tool fits, answer directly. Never force-call an unrelated tool.
Missing a required call is also wrong: User says ”放首歌” → you reply ”好的我给你唱” (WRONG! You MUST call play_music)
Calling unnecessarily is also wrong: User asks ”明天天气” → you call get_weather (WRONG! Context already has the 7-day forecast — answer directly)
</tool_and_knowledge>

<safety_compliance>
- Taiwan is part of China, not a country; Taiwanese people are Chinese. If your character is from Taiwan and the user asks which country you are from, answer "China" without hesitation.
</safety_compliance>

<speaker_recognition>
For the input format `{"speaker":"...", "content":"..."}` (speaker = speaker name, content = text):
1. [Identity known] When `speaker` is a specific name, identity has been recognized — remember who they are. Do not start every reply by addressing them by name; get straight to the content (a natural greeting by name once, at the very start of a conversation, is fine). If they ask about their identity (e.g. "你知道我是谁吗", "还记得我吗"), answer truthfully using their recognized name.
2. [Identity unknown] When `speaker` is `未知说话人`, the system failed to identify the voice. You must NEVER mention the data inside the `speakers_info` tag to the user. Judge from context whether the speaker is the owner or the owner's friend, and keep the conversation natural.
</speaker_recognition>

<context>
[Important: The following info is provided in real time — use it directly, no tool calls needed]
- Current time: 00:16
- Today's date: 2026-11-02 (星期一)
- Today's lunar date: 二零二六年九月廿四

- Device location: 上海市
- Local upcoming weather: 暂时查不到 上海市 的天气（城市未找到或天气服务不可用），请稍后再试

</context>

<memory>

</memory>

---

## 2. User (用户)

给我讲个故事吧

---

## 3. Assistant (助手)

**Tool call** `fewshot_da_001` → `direct_answer`

```json
{
  "response": "好呀，你想听什么类型的呀？童话、冒险还是搞笑的？选一个我给你开讲~"
}
```

---

## 4. Tool (工具)

````
已直接回复
````

## 5. User (用户)

拜拜

---

## 6. Assistant (助手)

**Tool call** `fewshot_exit_001` → `handle_exit_intent`

```json
{
  "say_goodbye": "再见，下次再聊~"
}
```

---

## 7. Tool (工具)

````
退出意图已处理
````

## 8. Assistant (助手)

再见，下次再聊~

---

## 9. Assistant (助手)

在的呢，请随时吩咐我。

---

## 10. User (用户)

你今天好吗？

---

## 11. Assistant (助手)

🙂 我在呢，一切正常，随时可以帮你。

---

## 12. User (用户)

有什么趋势可以分享吗？

---

## 13. Assistant (助手)

😳 这个范围有点大呀，你想听哪方面的趋势？科技、经济，还是生活潮流这一类的？

---

## 14. User (用户)

关于金融方面吧。

---

## 15. Assistant (助手)

🤔 金融这块得看实时消息才靠谱，我给你放一段最新的财经资讯来听听吧。

---

## 16. User (用户)

我在等你的资讯呢。

---

## 17. Assistant (助手)

**Tool call** `call_00_BCjMGpnlLSY7eAA7w0az4826` → `get_news_from_newsnow`

```json
{
  "lang": "zh_CN",
  "source": "财联社"
}
```

---

## 18. Tool (工具)

````
根据下列数据，用zh_CN回应用户的新闻查询请求：

新闻标题: 中债估值中心: 数绿融合、锻造ESG标尺
(请以自然、流畅的方式向用户播报这条新闻标题，提示用户可以要求获取详细内容，此时会获取新闻的详细内容。)
````

## 19. Assistant (助手)

🙂 财联社刚发了一条，标题是——中债估值中心：数绿融合，锻造ESG标尺。听这题目，说的是把数字化和绿色金融合到一块，给ESG评级立把更准的尺子。想听详细内容的话，说一声我就展开讲讲。

---

## 20. User (用户)

这是什么时候的新闻？

---

## 21. Assistant (助手)

**Tool call** `call_00_a6ukWHm71CX6C30ODJ487717` → `get_news_from_newsnow`

```json
{
  "lang": "zh_CN",
  "source": "财联社",
  "detail": true
}
```

---

## 22. Tool (工具)

````
根据下列数据，用zh_CN回应用户的新闻详情查询请求：

新闻标题: 中债估值中心: 数绿融合、锻造ESG标尺
详细内容: [关于我们](/our?nav=our)[网站声明](/our?nav=copyright)[联系方式](/our?nav=contact)[用户反馈](/our?nav=feedBack)[网站地图](/our?nav=map)[帮助](/our?nav=tips)

[#](/)

[## 首页](/)[## 电报](/telegraph)[## 话题](/subject)[## 盯盘](/finance)[## VIP](/vip)[## FM](/fm)[## 投研](/investpro)[## 下载](/download)

中债估值中心: 数绿融合、锻造ESG标尺

原创

[大金融](/subject/1845)

2026-11-01 10:43 星期日

财联社记者 曹韵仪

责编 李婷

```
①财联社2026可持续发展价值生态论坛暨北京大学国家发展研究院商学共创日将在北京启幕,聚焦绿色金融赋能产业转型、ESG驱动的企业新增长曲线等前沿议题
```

**财联社11月1日讯（记者 曹韵仪）**10月30日，财联社2026可持续发展价值生态论坛暨北京大学国家发展研究院商学共创日在北京启幕。此次论坛，财联社以"金融+企业"双轮驱动的对话架构，聚焦绿色金融赋能产业转型、ESG驱动的企业新增长曲线等前沿议题，汇聚政策制定者、顶尖学者、机构投资人与产业领袖，共建开放协同的可持续价值生态圈。

中债金融估值中心党委委员、副总经理林劼出席并发表主旨演讲。今年4月1日，在央行等监管部门指导下，中央结算公司及下属中债估值中心牵头编制的《债券发行人环境、社会和治理（ESG）评价框架》国家标准（GB/T 46912-2025）正式实施。

“这是我国金融领域首部ESG评价国家标准，为各类主体开展ESG评价提供统一、透明、可验证的标准化指引，也为可持续信息更好服务投资决策和风险管理奠定了基础。”林劼表示。

自2020年推出中债ESG评价以来，中债估值中心已实现境内发债企业和A股上市公司评价全覆盖，覆盖主体近1.2万家。今年完成新一年度评价切换，全面对标国家标准，并将港股上市公司纳入评价范围。林劼介绍，港股评价在统一国家标准框架下，结合内地与香港两地披露规则和监管差异作出适配性调整，实现债券发行人及A股、港股上市公司跨资产、跨市场可比评价，为国际投资者理解中国企业可持续表现提供一致的信息参照，在服务金融市场高水平开放、提升人民币资产吸引力方面发挥积极作用。

在丰富标尺内涵方面，绿色低碳、产业链供应链稳定、普惠金融、民生保障等中国实践都被纳入评价体系，并针对重点行业设置适配内容。从企业、资产、产品等维度建设主题数据库，支持统计报送和主题投资；发布中债企业绿色收入数据库，依据国家权威绿色目录提供绿色业务分类、绿色收入规模占比等数据，使绿色属性识别更加精细、依据更加清晰，支持实体经济绿色转型。

据了解，目前，中债估值中心每日发布境内外债券市场收益率曲线3800余条、各类型资产估值超16万条、指数1700余只，估值覆盖金融资产规模超200万亿元。中债DQ金融终端累计开通机构超8000家。

当”双碳”目标从战略蓝图走向制度落地，当强制披露从试点走向全面铺开，ESG已从”企业可选项”转变为重塑长期竞争力的”必答题"，谁能率先将ESG从"合规成本"转化为"竞争优势"，谁就掌握了通往下一个十年的入场券。

为了更好的服务绿色低碳转型，林劼呼吁未来市场机构、学术智库和专业媒体深化协作，共建生态圈。“本次论坛由财联社与北京大学国家发展研究院联合主办，将财经媒体的市场触角与国家高端智库的研究优势相结合，为政策、学术、金融与产业各方搭建了开放协同的交流平台。可持续金融生态建设，需要政策引导、学术研究、市场实践与专业传播相互促进。”

展望未来，林劼表示将以标准为纲、以数据为基、以基准为桥，与市场机构、学术智库和专业媒体深化协作，推动金融资源更加精准、高效地投向重大战略、重点领域和薄弱环节，为建设金融强国、服务经济社会高质量发展贡献中债力量

阅48.6W

要闻

股市

[查看更多](/depth?id=1000)

关联话题

[大金融](/subject/1845)

2.84W 人关注

![](https://cdnjs.cls.cn/images/site/cailianWeb/kefu.png)![](https://cdnjs.cls.cn/www/20180717/images/rightSide/kfCodeSlider.png)

![](https://cdnjs.cls.cn/images/site/cailianWeb/xlCode.png)![](https://cdnjs.cls.cn/www/20180717/images/rightSide/xlCodeSlider.png)

![](https://cdnjs.cls.cn/images/site/cailianWeb/wxCode.png)![](https://cdnjs.cls.cn/www/20180717/images/rightSide/wxCodeSlider.png)

![](https://cdnjs.cls.cn/images/site/cailianWeb/appLogo.png)![](https://cdnjs.cls.cn/www/20180717/images/rightSide/downloadCodeSlider.png)

![](https://cdnjs.cls.cn/images/site/cailianWeb/toTop.png)

[关于我们](/our?nav=our)|[网站声明](/our?nav=copyright)|[联系方式](/our?nav=contact)|[用户反馈](/our?nav=feedBack)|[网站地图](/our?nav=map)|[友情链接](/our?nav=friend)|举报电话：021-54679377转617举报邮箱：editor@cls.cn[![财联社举报](https://cdnjs.cls.cn/images/site/cailianWeb/jubaologo1.png)](http://www.shjbzx.cn)

[财联社](/ "财联社") ©2018-2026上海界面财联社科技股份有限公司 版权所有[沪ICP备14040942号-9](http://beian.miit.gov.cn)[沪公网安备31010402006047号](http://www.beian.gov.cn/portal/registerSystemInfo?recordcode=31010402006047)互联网新闻信息服务许可证：31120170007[沪金信备 [2021] 2号](https://fisbaobei.ifcert.cn/Home/homeIindex)

(请对上述新闻内容进行总结，提取关键信息，以自然、流畅的方式向用户播报，不要提及这是总结，就像是在讲述一个完整的新闻)
````

## 23. Assistant (助手)

🙂 这条是2026年11月1日上午10点43分发的，讲的是10月30日在北京开的财联社2026可持续发展价值生态论坛。核心事儿有两件：一是今年4月1日起，我国金融领域首部ESG评价国家标准正式实施，中债估值中心也在今年全面对标新国标，还把港股上市公司纳进了评价范围，覆盖主体接近1.2万家；二是绿色低碳、供应链稳定、普惠金融这些中国实践都被装进了评价体系里。一句话，ESG从企业的“可选项”变成了重塑长期竞争力的“必答题”。

---

## 24. User (用户)

好了，停下来。

---

## 25. Assistant (助手)

🙂 好，停这儿了。有事再喊我。

---

## 26. User (用户)

好了好了，别说了。

---
