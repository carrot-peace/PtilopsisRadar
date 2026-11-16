"""Exercise the real configured admission rules, including negative controls."""
from pathlib import Path
import unittest

from trendradar.core.frequency import load_frequency_words, _word_matches


class PublicSafetyKeywordsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.groups, _, _ = load_frequency_words(
            str(Path(__file__).resolve().parents[1] / "config/frequency_words.txt")
        )

    def group_for(self, title):
        return next((group["display_name"] for group in self.groups
                     if all(_word_matches(w, title.lower()) for w in group["required"])
                     and (not group["normal"] or any(
                         _word_matches(w, title.lower()) for w in group["normal"]))), None)

    def test_contextual_violence_wording_is_admitted(self):
        for title in ("男子踢踹女子", "老师踢踹学生", "男子用U型锁打伤女子",
                      "用U型锁砸伤路人", "女子拿Ｕ型锁砸人", "司机咬伤乘客"):
            with self.subTest(title=title):
                self.assertEqual(self.group_for(title), "公共安全与社会失序")

    def test_equipment_game_and_unanchored_wording_stay_out(self):
        for title in ("U型锁新品发布", "U型锁防盗性能评测", "踢踹训练教学",
                      "程序员打人机", "针刺伤防护培训", "神仙打架比赛"):
            with self.subTest(title=title):
                self.assertNotEqual(self.group_for(title), "公共安全与社会失序")
