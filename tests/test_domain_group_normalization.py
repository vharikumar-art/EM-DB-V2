from app.utils.csv_utils import normalize_domain_group


def test_normalize_domain_group_handles_mixed_separators_and_aliases():
    assert normalize_domain_group("IT, Data Science") == ["IT", "Data Science"]
    assert normalize_domain_group("IT; Agriculture") == ["IT", "Agriculture"]
    assert normalize_domain_group("Data Science / Agriculture") == ["Data Science", "Agriculture"]
    assert normalize_domain_group("IT & Agriculture") == ["IT", "Agriculture"]
    assert normalize_domain_group("it; agri") == ["IT", "Agriculture"]
    assert normalize_domain_group("unknown / Data Science") == ["Data Science"]
    assert normalize_domain_group("IT, IT, Data Science") == ["IT", "Data Science"]
