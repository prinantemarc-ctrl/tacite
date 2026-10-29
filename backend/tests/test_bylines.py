"""Bylines : noms de personnes, agences, multi-auteurs."""

from app.services.rss import clean_author_name, looks_like_person_name, split_author_names


class TestLooksLikePersonName:
    def test_plain_name(self):
        ok, n = looks_like_person_name("Jean Dupont")
        assert ok and n == "Jean Dupont"

    def test_article_redige_par(self):
        ok, _ = looks_like_person_name("Article rédigé par")
        assert not ok

    def test_agency(self):
        assert looks_like_person_name("Agence France-Presse")[0] is False


class TestCleanAuthorName:
    def test_prefix_par(self):
        assert clean_author_name("Par Marie Martin") == "Marie Martin"

    def test_article_redige_par_dropped(self):
        assert clean_author_name("Article rédigé par") is None

    def test_agency_dropped(self):
        assert clean_author_name("AFP") is None
        assert clean_author_name("Reuters") is None

    def test_multi_authors_kept_as_first_when_comma_role(self):
        assert clean_author_name("Claire Dubois, correspondante") == "Claire Dubois"


class TestSplitAuthorNames:
    def test_et(self):
        names = split_author_names("Jean Dupont et Marie Martin")
        assert names == ["Jean Dupont", "Marie Martin"]

    def test_and(self):
        names = split_author_names("John Smith and Jane Doe")
        assert "John Smith" in names and "Jane Doe" in names

    def test_agency_stripped(self):
        assert split_author_names("Article rédigé par") == []
