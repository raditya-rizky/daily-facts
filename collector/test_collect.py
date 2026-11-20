"""Tests for the DYK collector. Fixtures are real lines from Wikipedia's Oct 2025 archive and nomination pages."""
import unittest

from collect import apply_hidden, clean, fact_id, find_source, parse_archive, short_source

ARCHIVE = """==Did you know...==
===31 October 2025===
*'''''12:00, 31 October 2025 (UTC)'''''

* ... that '''[[Portrait of Gregor Baci|a Hungarian nobleman]]''' ''(pictured)'' survived with a spear in his head?
* ... that '''''[[Friday the 13th (1980 film)|Friday the 13th]]''''' has been credited for popularizing a trope?
* ... that the flatworm '''''[[Freddius]]''''' is named after [[Freddy Krueger]]'s razor gloves?
* ... that a hook with no bold link is skipped?
===30 October 2025===
* ... that '''[[lysine malonylation]]''' is a thing{{'}}s?
"""

NOM_BACI = """{{DYK nompage|Portrait of Gregor Baci}}
* ... that '''[[Portrait of Gregor Baci|a Hungarian nobleman]]''' ''(pictured)'' survived with a spear in his head?
* Source: Missmann, Martin; Tauscher, Thomas (2010). "[https://www.thelancet.com/journals/lancet/article/PIIS0140-6736(09)60294-4/fulltext Impaled head]". The Lancet. 375 (9711)}}
|sourced          = n
"""

NOM_ALTS = """* ... that ''[[The New York Times]]'' compared '''[[Reba Paeff Mirsky]]''' to having "two right hands and two left hands"? <small>Source: [https://www.proquest.com/docview/114384805 The clavichord's tone]</small>
** '''ALT1''': ... that musician '''[[Reba Paeff Mirsky]]''' wrote a trilogy of children's books inspired by Zulu girls? <small>Source: [https://www.proquest.com/docview/117272221 Some other article]</small>
"""


class TestClean(unittest.TestCase):
    def test_links_bold_pictured(self):
        self.assertEqual(
            clean("... that '''[[Portrait of Gregor Baci|a Hungarian nobleman]]''' ''(pictured)'' survived?"),
            "... that a Hungarian nobleman survived?")

    def test_templates(self):
        self.assertEqual(clean("Kawamura{{'}}s video ran {{convert|5|km|mi}} {{nowrap|in total}}"),
                         "Kawamura's video ran 5 km in total")

    def test_question_and_possessive_templates(self):
        self.assertEqual(clean("''Undine''{{`s}} crew fled{{-?}}"), "Undine's crew fled?")

    def test_unknown_template_rejected(self):
        self.assertIsNone(clean("a {{someweirdthing|x|y}} b"))


class TestParseArchive(unittest.TestCase):
    def test_parse(self):
        facts = parse_archive(ARCHIVE)
        self.assertEqual(len(facts), 4)  # the hook with no bold link is skipped
        f = facts[0]
        self.assertEqual(f["date"], "2025-10-31")
        self.assertEqual(f["article"], "Portrait of Gregor Baci")
        self.assertEqual(f["text"], "... that a Hungarian nobleman survived with a spear in his head?")
        self.assertEqual(f["article_url"], "https://en.wikipedia.org/wiki/Portrait_of_Gregor_Baci")
        self.assertEqual(facts[1]["article"], "Friday the 13th (1980 film)")
        self.assertEqual(facts[2]["text"], "... that the flatworm Freddius is named after Freddy Krueger's razor gloves?")
        self.assertEqual(facts[3]["date"], "2025-10-30")
        self.assertEqual(facts[3]["article"], "Lysine malonylation")  # first letter capitalised like Wikipedia titles


class TestShortSource(unittest.TestCase):
    def test_plain_citation_with_link(self):
        short, url, cit = short_source('Missmann, Martin (2010). "[https://www.thelancet.com/x Impaled head]". The Lancet. 375')
        self.assertEqual(short, "Impaled head (2010)")
        self.assertEqual(url, "https://www.thelancet.com/x")
        self.assertIn("The Lancet", cit)

    def test_cite_template(self):
        short, url, _ = short_source(
            "{{Cite news |date=January 31, 2018 |title=Forty years of corruption |work=[[Hot Springs Sentinel-Record]] "
            "|url=https://www.hotsr.com/news/2018/x |url-status=live}}")
        self.assertEqual(short, "Hot Springs Sentinel-Record (2018)")
        self.assertEqual(url, "https://www.hotsr.com/news/2018/x")

    def test_cite_nested_template(self):
        short, url, _ = short_source(
            "{{cite news |date=1965-05-04 |title=Cycling |newspaper=[[South China Morning Post]] |page=3 |id={{ProQuest|1507205251}} }}")
        self.assertEqual(short, "South China Morning Post (1965)")
        self.assertEqual(url, "")

    def test_book_without_link(self):
        short, url, _ = short_source(
            "Bradshaw, Richard; Rius, Juan Fandos (2016). Historical Dictionary of the Central African Republic (Historical "
            "Dictionaries of Africa). Rowman & Littlefield. p 134")
        self.assertEqual(short, "Historical Dictionary of the Central African Republic (Historical Dictionaries of Africa) (2016)")
        self.assertEqual(url, "")

    def test_bare_url(self):
        self.assertEqual(short_source("https://apnews.com/article/sweden-moon-house"),
                         ("apnews.com", "https://apnews.com/article/sweden-moon-house", "https://apnews.com/article/sweden-moon-house"))

    def test_labelled_and_generic_label(self):
        self.assertEqual(short_source("[https://www.oricon.co.jp/news/2357227/full Oricon] some quote")[0], "Oricon")
        self.assertEqual(short_source("[https://www.channelnewsasia.com/asia/x source]")[0], "channelnewsasia.com")
        self.assertEqual(short_source("[https://www.musicradar.com/news/x ''MusicRadar'']")[0], "MusicRadar")

    def test_quote_only_is_empty(self):
        self.assertEqual(short_source('"Nothing of greater historical interest attaches to Long Lake."'), ("", "", ""))


class TestFindSource(unittest.TestCase):
    def test_source_on_next_line(self):
        short, url, _ = find_source(NOM_BACI, "... that a Hungarian nobleman survived with a spear in his head?")
        self.assertEqual(short, "Impaled head (2010)")
        self.assertTrue(url.startswith("https://www.thelancet.com/"))

    def test_picks_the_alt_that_ran(self):
        _, url, _ = find_source(NOM_ALTS, "... that musician Reba Paeff Mirsky wrote a trilogy of children's books inspired by Zulu girls?")
        self.assertEqual(url, "https://www.proquest.com/docview/117272221")
        _, url, _ = find_source(NOM_ALTS, '... that The New York Times compared Reba Paeff Mirsky to having "two right hands and two left hands"?')
        self.assertEqual(url, "https://www.proquest.com/docview/114384805")

    def test_source_before_hook_text_is_ignored(self):
        nom = "::Source: says ... that a Hungarian nobleman survived with a spear in his head?\n" + NOM_BACI
        self.assertEqual(find_source(nom, "... that a Hungarian nobleman survived with a spear in his head?")[0],
                         "Impaled head (2010)")

    def test_revised_hook_wins_over_struck_original(self):
        nom = ("* <s>... that '''[[Matthew Vickers]]''' made his debut in Italy singing in the French opera Carmen?</s>\n"
               "* '''ALT1''': ... that '''[[Matthew Vickers]]''' made his debut in Italy singing in French?\n"
               "* Source: Vickers [https://www.operascout.com/x operascout profile] says so\n")
        self.assertEqual(find_source(nom, "... that Matthew Vickers made his debut in Italy singing in French?")[1],
                         "https://www.operascout.com/x")

    def test_label_with_unknown_template(self):
        self.assertEqual(short_source("[https://www.example.org/x {{weird|thing}}]")[0], "example.org")

    def test_www_label(self):
        self.assertEqual(short_source("[https://www.ouraynews.com/x www.ouraynews.com]")[0], "ouraynews.com")

    def test_no_match(self):
        self.assertEqual(find_source(NOM_BACI, "... that something completely unrelated happened in Peru?"), ("", "", ""))
        self.assertEqual(find_source("", "... that x?"), ("", "", ""))


class TestIdsAndHidden(unittest.TestCase):
    def test_id_stable(self):
        self.assertEqual(fact_id("... that x?"), fact_id("... that x?"))
        self.assertEqual(len(fact_id("... that x?")), 8)
        self.assertNotEqual(fact_id("... that x?"), fact_id("... that y?"))

    def test_apply_hidden(self):
        facts = [{"id": "aaaa1111"}, {"id": "bbbb2222"}]
        self.assertEqual(apply_hidden(facts, {"bbbb2222"}), [{"id": "aaaa1111"}])


if __name__ == "__main__":
    unittest.main()
