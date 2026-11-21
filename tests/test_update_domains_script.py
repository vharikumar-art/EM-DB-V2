import pytest

from update_domains_script import order_sources


def test_order_sources_preserves_direct_targets_for_mapping_chains():
    mapping = {
        "A": ("B", {"a"}),
        "B": ("C", {"b"}),
        "C": ("C", {"c"}),
    }

    ordered = order_sources(mapping, {"A": 1, "B": 1})

    assert ordered.index("B") < ordered.index("A")


def test_order_sources_rejects_cycles():
    mapping = {
        "A": ("B", {"a"}),
        "B": ("A", {"b"}),
    }

    with pytest.raises(ValueError, match="Cyclic domain mapping"):
        order_sources(mapping, {})
