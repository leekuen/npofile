"""組織分類表與自動分類規則（口徑見 tickets/LK-09）：兩層領域（大類 › 小類）＋服務對象。

代號：大類 `culture`、小類 `culture.ethnic`、服務對象 `target.indigenous`。
官方：衛福部「勸募用途」→ 大類。推測：組織名稱與近 5 年勸募活動名稱的關鍵字 → 小類與服務對象（有小類就帶上它的大類）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    """pattern 命中、而且（有 requires 的話）requires 也命中、unless 沒命中，才算。"""

    pattern: str
    requires: str = ""
    unless: str = ""

    def match(self, text: str) -> bool:
        if not re.search(self.pattern, text):
            return False
        if self.requires and not re.search(self.requires, text):
            return False
        return not (self.unless and re.search(self.unless, text))


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    rule: Rule | None = None
    subs: tuple["Category", ...] = field(default_factory=tuple)


ANIMAL_CONTEXT = r"動物|犬|貓|狗|毛孩|寵物|浪浪|浪貓|浪犬"
INTL_CONTEXT = r"國際|世界|全球|海外|跨國|亞洲|非洲"

FIELDS: tuple[Category, ...] = (
    Category("welfare", "社會福利", Rule(r"社會福利|社福|慈善|福利基金會|關懷協會|救助協會"), (
        Category("welfare.economic", "經濟扶助", Rule(r"扶貧|濟貧|脫貧|食物銀行|實物銀行|物資|助貧")),
        Category("welfare.family", "家庭支持", Rule(r"家庭|家扶|親職|單親")),
        Category("welfare.longterm", "長期照顧", Rule(r"長照|長期照顧|安養|養護|護理之家|日間照顧|日照中心|照顧服務")),
        Category("welfare.emergency", "急難救助", Rule(r"急難|救難|救援隊|搜救|賑災|災民|災後", unless=ANIMAL_CONTEXT)),
        Category("welfare.employment", "就業與培力", Rule(r"就業|庇護工場|職訓|職業重建|培力")),
    )),
    Category("education", "教育", Rule(r"教育|文教|學苑|書院|學校|國小|國中|高中|大學"), (
        Category("education.tutoring", "學童課輔與助學", Rule(r"課輔|課後|助學|獎學|清寒學|學童")),
        Category("education.special", "特殊教育", Rule(r"特殊教育|特教|啟智|啟聰|啟明")),
        Category("education.reading", "閱讀與圖書", Rule(r"閱讀|圖書|讀書會|書屋|繪本")),
        Category("education.vocational", "技職培力", Rule(r"技職|職業訓練|技能|職能")),
        Category("education.research", "學術研究", Rule(r"研究|學術")),
    )),
    Category("culture", "文化藝術", Rule(r"文化|藝文|藝術|文史"), (
        Category("culture.ethnic", "族群文化", Rule(r"原住民.*(文化|藝術|傳統|語言|歌舞|樂舞)|客家|族群|部落.*文化|族語|新住民文化")),
        Category("culture.heritage", "傳統文化與文資", Rule(r"文化資產|古蹟|文資|傳統|民俗|陣頭|宗祠")),
        Category("culture.local", "在地文史", Rule(r"文史|地方文化|社區營造|鄉土|地方學")),
        Category("culture.performing", "表演藝術", Rule(r"劇團|劇場|劇坊|舞團|舞蹈|音樂|合唱|樂團|國樂|管樂|弦樂|戲曲|布袋戲|歌仔戲|京劇|說唱")),
        Category("culture.visual", "視覺藝術", Rule(r"美術|攝影|書畫|書法|畫會|繪畫|雕塑|陶藝")),
        Category("culture.literature", "文學出版", Rule(r"文學|出版|詩社|作家")),
    )),
    Category("health", "醫療健康", Rule(r"醫療|醫學|醫院|健康|保健|病友"), (
        Category("health.disease", "疾病照護", Rule(r"癌|罕見|罕病|腎|糖尿|失智|病友|血友|肝病|心臟|愛滋|安寧|帕金森|漸凍|地中海")),
        Category("health.mental", "心理健康", Rule(r"心理|精神|自殺防治|憂鬱|生命線|張老師")),
        Category("health.rural", "偏鄉醫療", Rule(r"偏鄉醫療|醫療服務隊|巡迴醫療|離島醫療")),
        Category("health.public", "公共衛生", Rule(r"衛生|防疫|健康促進|戒菸|捐血|器官捐贈|口腔")),
    )),
    Category("environment", "環境保護", Rule(r"環境|環保|自然|生態"), (
        Category("environment.ecology", "生態保育", Rule(r"生態|保育|濕地|溼地|鳥會|野鳥|蝴蝶|螢火蟲", unless=r"野生動物")),
        Category("environment.ocean", "海洋", Rule(r"海洋|海岸|淨灘|珊瑚", unless=r"扶輪社|遊憩|潛水")),
        Category("environment.forest", "森林綠化", Rule(r"森林|植樹|綠化|種樹|綠美化")),
        Category("environment.pollution", "污染防治", Rule(r"污染|汙染|空氣品質|廢棄物|垃圾|減塑|資源回收")),
        Category("environment.climate", "氣候與能源", Rule(r"氣候|能源|減碳|節能|再生能源|淨零")),
        Category("environment.education", "環境教育", Rule(r"環境教育|自然教育|生態教育")),
    )),
    Category("animal", "動物保護", Rule(r"動物|寵物|毛孩|浪浪"), (
        Category("animal.stray", "流浪動物救援", Rule(r"流浪|浪浪|浪犬|浪貓|毛孩|救援", requires=ANIMAL_CONTEXT)),
        Category("animal.shelter", "收容與送養", Rule(r"收容|送養|認養|中途", requires=ANIMAL_CONTEXT)),
        Category("animal.wildlife", "野生動物保育", Rule(r"野生動物|海龜|鯨|豚|石虎|黑熊|猛禽|穿山甲")),
        Category("animal.welfare", "動物福利倡議", Rule(r"動物福利|動物權|動物保護|動保")),
    )),
    Category("international", "國際援助", Rule(r"國際(人道|援助|救援|合作|發展|志工)|世界展望|人道"), (
        Category("international.humanitarian", "人道救援", Rule(r"人道|難民|救援|援助|賑災", requires=INTL_CONTEXT)),
        Category("international.development", "國際發展", Rule(r"國際發展|國際合作|國際志工|海外志工")),
    )),
    Category("rights", "人權與公民", Rule(r"人權|平權|公民|民主", unless=r"黨|監督委員|勞工退休|土地公"), (
        Category("rights.gender", "性別平權", Rule(r"性別|平權|同志|婦女新知|婦女權益|女權")),
        Category("rights.judicial", "司法人權", Rule(r"司法|人權|冤獄|法律扶助|廢除死刑|廢死|受刑人")),
        Category("rights.civic", "公民參與", Rule(r"公民|民主|監督|開放政府|透明|審議", unless=r"黨|監督委員|勞工退休|土地公")),
    )),
    Category("other", "非公益類", None, (
        Category("other.religion", "宗教", Rule(
            r"[宮寺廟庵]|教會|佛|道教|基督|天主|禪|宗教|伊斯蘭|清真|一貫道|聖母|媽祖|關帝|土地公|福德|堂$", unless=r"故宮|宮崎|東宮")),
        Category("other.trade", "公會／產業團體", Rule(r"公會|商會|工會|同業|產業|工業會|商業會|會計師|律師公會|勞工退休準備金|職工福利")),
        Category("other.sports", "體育", Rule(r"體育|運動|(?<![地全寰星眼])球|田徑|武術|太極|登山|游泳|馬拉松|自行車|單車|棋|射箭|跆拳|柔道|划船|龍舟")),
        Category("other.community", "社區", Rule(r"社區發展|守望相助|宗親|同鄉|校友|聯誼|里民|鄰里")),
    )),
)

TARGETS: tuple[Category, ...] = (
    Category("target.children", "兒童少年", Rule(r"兒童|少年|兒少|青少年|學童|孩童|幼兒|育幼|孤兒|孩子")),
    Category("target.elderly", "長者", Rule(r"老人|長者|銀髮|長青|高齡|樂齡|安養|老年")),
    Category("target.disability", "身心障礙", Rule(
        r"身心障礙|身障|視障|聽障|智障|智能障礙|自閉|唐氏|脊髓損傷|肢障|心智障礙|啟智|啟聰|啟明|植物人|腦性麻痺|腦麻|盲人|聾|手語")),
    Category("target.women", "婦女", Rule(r"婦女|女性|媽媽|母親|單親媽")),
    Category("target.indigenous", "原住民", Rule(
        r"原住民|部落|阿美|泰雅|排灣|布農|卑南族|魯凱|鄒族|賽夏|達悟|雅美|太魯閣|撒奇萊雅|賽德克|邵族|噶瑪蘭|拉阿魯哇|卡那卡那富|平埔|族人")),
    Category("target.immigrants", "新住民", Rule(r"新住民|新移民|外籍配偶|移工|移民")),
    Category("target.rural", "偏鄉", Rule(r"偏鄉|偏遠|離島|山地|山區")),
    Category("target.poor", "弱勢家庭", Rule(r"弱勢|清寒|貧困|低收入|中低收|扶貧|脫貧|急難")),
)

# 衛福部「勸募用途」→ 大類（「其他經主管機關認定之事業」不對到任何大類）
OFFICIAL_PURPOSES = {
    "社會福利事業/社會慈善事業": "welfare",
    "教育事業": "education",
    "文化事業": "culture",
    "醫療保健事業": "health",
    "環境保護事業": "environment",
    "動物保護事業": "animal",
    "援外或國際人道救援": "international",
}

LABELS: dict[str, str] = {}
PARENT: dict[str, str] = {}
for _f in FIELDS:
    LABELS[_f.code] = _f.label
    for _s in _f.subs:
        LABELS[_s.code] = _s.label
        PARENT[_s.code] = _f.code
for _t in TARGETS:
    LABELS[_t.code] = _t.label

OFFICIAL, INFERRED = "official", "inferred"


def is_target(code: str) -> bool:
    return code.startswith("target.")


def dimension(code: str) -> str:
    return "target" if is_target(code) else "field"


def official_codes(purposes: str) -> set[str]:
    return {OFFICIAL_PURPOSES[p.strip()] for p in (purposes or "").split("、") if p.strip() in OFFICIAL_PURPOSES}


NAME_ONLY_FIELDS = {"other"}  # 「這是哪種組織」只看組織名稱：活動名稱寫「社區發展計畫」不代表它是社區團體


def infer_codes(texts: list[str]) -> set[str]:
    """名稱類的短文字逐段比對（不把好幾段串起來，避免跨段湊出關鍵字）。texts[0] 是組織名稱。"""
    codes: set[str] = set()
    for i, text in enumerate(texts):
        text = (text or "").strip()
        if not text:
            continue
        for f in FIELDS:
            if i > 0 and f.code in NAME_ONLY_FIELDS:
                continue
            for s in f.subs:
                if s.rule and s.rule.match(text):
                    codes.add(s.code)
                    codes.add(f.code)
            if f.rule and f.rule.match(text):
                codes.add(f.code)
        for t in TARGETS:
            if t.rule.match(text):
                codes.add(t.code)
    return codes


def classify(name: str, purposes: str = "", project_names: list[str] | None = None) -> dict[str, str]:
    """回傳 {代號: 來源}；官方優先於推測。"""
    result = {c: INFERRED for c in infer_codes([name, *(project_names or [])])}
    for c in official_codes(purposes):
        result[c] = OFFICIAL
    return result
