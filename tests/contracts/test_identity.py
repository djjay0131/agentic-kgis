import pytest
from pydantic import ValidationError

from kg_contracts.evidence import Provenance
from kg_contracts.identity import (
    EntityRef,
    IdentityError,
    IdentityLink,
    IdentityLinkKind,
    is_identity_id,
    new_identity_id,
    parse_identity_id,
)

PROV = Provenance(source="unit-test", actor="tester")


def test_new_identity_id_shape():
    iid = new_identity_id("baseball")
    assert iid.startswith("kg://baseball/identity/")
    graph, ulid = parse_identity_id(iid)
    assert graph == "baseball" and len(ulid) == 26


def test_identity_id_rejects_bad_graph_id():
    with pytest.raises(IdentityError, match="Baseball"):
        new_identity_id("Baseball")  # graph ids are lowercase


def test_is_identity_id():
    assert is_identity_id(new_identity_id("traffic"))
    assert not is_identity_id("Player:usssa:12345")
    assert not is_identity_id("kg://traffic/other/01H")


def test_parse_rejects_naming_offender():
    with pytest.raises(IdentityError, match="not-an-id"):
        parse_identity_id("not-an-id")


def test_entity_ref_valid_and_renders_namespaced():
    ref = EntityRef(entity_type="Paper", namespace="doi", key="10.1145/3292500")
    assert ref.render() == "Paper:doi:10.1145/3292500"


def test_entity_ref_key_may_contain_colons():
    ref = EntityRef.parse("Doc:arxiv:2501.1234:v2")
    assert (ref.entity_type, ref.namespace, ref.key) == ("Doc", "arxiv", "2501.1234:v2")


def test_entity_ref_rejects_non_pascal_type_and_bad_namespace():
    with pytest.raises(ValidationError):
        EntityRef(entity_type="paper", namespace="doi", key="x")
    with pytest.raises(ValidationError):
        EntityRef(entity_type="Paper", namespace="DOI", key="x")
    with pytest.raises(ValidationError):
        EntityRef(entity_type="Paper", namespace="doi", key="  ")


def test_bare_label_key_is_rejected_with_namespace_message():
    # the deprecated v1 format must fail loudly, naming the offender
    with pytest.raises(IdentityError, match="Player:123"):
        EntityRef.parse("Player:123")
    with pytest.raises(IdentityError, match="namespace"):
        EntityRef.parse("Player:123")


def test_free_text_rejected_naming_offender():
    with pytest.raises(IdentityError, match="Main St & 1st"):
        EntityRef.parse("Main St & 1st")  # agentic-tskg failure mode


def test_trailing_newline_identity_id_rejected():
    # `$` alone also matches before a trailing newline in Python re;
    # the patterns must use fullmatch so "...\n" is rejected, not coerced.
    iid_nl = new_identity_id("baseball") + "\n"
    assert not is_identity_id(iid_nl)
    with pytest.raises(IdentityError, match="baseball"):
        parse_identity_id(iid_nl)


def test_trailing_newline_graph_id_rejected():
    with pytest.raises(IdentityError, match="baseball"):
        new_identity_id("baseball\n")


def test_identity_link_rejects_trailing_newline_endpoint():
    a = new_identity_id("baseball")
    b = new_identity_id("traffic") + "\n"
    with pytest.raises(ValidationError, match="identity"):
        IdentityLink(left_identity=a, right_identity=b,
                     kind=IdentityLinkKind.SAME_AS, authority="x", provenance=PROV)


def test_identity_link_valid_cross_graph():
    a = new_identity_id("baseball")
    b = new_identity_id("agentic-kg")
    link = IdentityLink(
        left_identity=a, right_identity=b,
        kind=IdentityLinkKind.POSSIBLY_SAME_AS,
        authority="orcid", provenance=PROV,
    )
    assert link.link_id.startswith("il_")
    assert link.kind is IdentityLinkKind.POSSIBLY_SAME_AS


def test_identity_link_rejects_non_identity_endpoints_and_self_link():
    a = new_identity_id("baseball")
    with pytest.raises(ValidationError, match="identity"):
        IdentityLink(left_identity="Player:usssa:1", right_identity=a,
                     kind=IdentityLinkKind.SAME_AS, authority="x", provenance=PROV)
    with pytest.raises(ValidationError, match="itself"):
        IdentityLink(left_identity=a, right_identity=a,
                     kind=IdentityLinkKind.SAME_AS, authority="x", provenance=PROV)
