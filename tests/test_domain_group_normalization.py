from app.utils.csv_utils import normalize_domain_group


def test_normalize_domain_group_handles_mixed_separators_and_aliases():
    assert normalize_domain_group("IT, Data Science") == ["IT", "Data Science"]
    assert normalize_domain_group("IT; Agriculture") == ["IT", "Agriculture"]
    assert normalize_domain_group("Data Science / Agriculture") == ["Data Science", "Agriculture"]
    assert normalize_domain_group("IT & Agriculture") == ["IT", "Agriculture"]
    assert normalize_domain_group("it; agri") == ["IT", "Agriculture"]
    assert normalize_domain_group("unknown / Data Science") == ["Data Science"]
    assert normalize_domain_group("IT, IT, Data Science") == ["IT", "Data Science"]
    assert normalize_domain_group("Medical") == ["Medicine"]


def test_domain_group_does_not_copy_legacy_domain_value_when_category_field_is_present():
    df = __import__('pandas').DataFrame([
        {
            "email": "test@example.com",
            "domain": "IT",
            "fieldCategory": "IT & Agriculture",
        }
    ])
    valid_rows, invalid_rows = __import__('app.utils.csv_utils', fromlist=['validate_and_clean_rows']).validate_and_clean_rows(df)

    assert valid_rows[0]["domain_group"] == ["IT", "Agriculture"]
    assert valid_rows[0]["domain"] == "IT"
    assert invalid_rows == []
