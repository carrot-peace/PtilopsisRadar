"""Esports context recognition, independent of heat or public-interest overrides."""

import re
import unicodedata
from typing import Any, Iterable, Mapping


_CONTEXT = re.compile(
    r"电竞|英雄联盟|王者荣耀|无畏契约|德玛西亚杯|德杯|进化者杯|"
    r"上海(?:全球)?冠军赛|全球总决赛|数据雷达图|赛后数据|S赛|"
    r"(?<![a-z])(?:LPL|LCK|LEC|KPL|VCT(?:CN)?|IVL|HLTV|CSGO|CS2|DOTA2?)(?![a-z])|"
    r"(?<![a-z0-9])S\d{1,2}(?:全球|赛|决赛|瑞士轮|淘汰赛|应援|全赛区|开赛)|"
    r"(?:20\d{2})?Major(?:重返|落地)|CS\s*Major|IEM北京",
    re.I,
)
_TEAMS = (
    "上海EDG.M", "广州TTG", "重庆狼队", "长沙TES.A", "北京WB", "FPX.ZQ",
    "LGDNBW", "EDGM", "100T", "Vitality", "MOUZ", "KSG",
    "NAVI", "BLG", "KBG", "LGD", "TES", "EDG", "JDG", "GenG",
    "HLE", "PRX", "MVK", "BFX", "MRC", "TYLOO", "FaZe",
    "TLAW", "MKOI", "WSIG", "T1", "G2", "C9",
)
_TEAM = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(
        re.escape(team) + (r"(?![a-z0-9]|-\d)" if len(team) <= 3 else r"(?![a-z])")
        for team in _TEAMS
    ) + r")",
    re.I,
)
# Short English words and technology acronyms need competitive context.
_AMBIGUOUS = re.compile(
    r"(?<![a-z0-9])(?:IG|iG|AL|WE|KC|GE|NS|KT|DK|VIT|RED|AQ|GEN|MSI|Spirit|"
    r"NRG|LOUD|FLY|FUR|Falcons)(?![a-z])"
)
_COMPETITIVE = re.compile(
    r"vs\b|对战|对阵|迎战|战胜|击败|夺冠|冠军|出征|赛|淘汰|横扫|零封|"
    r"力克|取胜|晋级|队服|队友|地图|葬送|拿下|[0-5]\s*[:：-]\s*[0-5]", re.I
)
_PEOPLE = re.compile(
    r"(?<![a-z0-9])(?:Faker|donk|NiKo|Kyxsan|Zuian|"
    r"Daeny|Jinggg|Smoggy|happywei)(?![a-z])|"
    r"管泽元|Bin哥|宁王|一诺状态|369(?:回国|紧急|出征)|"
    r"滔搏|CS主播茄子|Shy粉|1酱赛评|1酱评", re.I
)
_AMBIGUOUS_PEOPLE = re.compile(
    r"(?<![a-z0-9])(?:Knight|Viper|Elk|Canyon|nobody)(?![a-z])", re.I
)
_PLAYER_ACTIVITY = re.compile(r"状态|开播|首播|选手|战队|队友|赛区|电竞")


def esports_context(text: str) -> bool:
    text = unicodedata.normalize("NFKC", str(text or ""))
    return bool(
        _CONTEXT.search(text) or _TEAM.search(text) or _PEOPLE.search(text)
        or (_AMBIGUOUS.search(text) and _COMPETITIVE.search(text))
        or (_AMBIGUOUS_PEOPLE.search(text)
            and (_COMPETITIVE.search(text) or _PLAYER_ACTIVITY.search(text)))
    )


def esports_item(topic: str, samples: Iterable[Any] | None = None) -> bool:
    """Check every available title; never infer esports from a generic group name."""
    if esports_context(topic):
        return True
    return any(
        esports_context(s.get("title", "") if isinstance(s, Mapping) else s)
        for s in samples or ()
    )
