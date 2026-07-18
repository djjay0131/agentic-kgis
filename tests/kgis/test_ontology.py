"""Coverage reports in two directions — unknown terms (the data drifted) and
unused terms (the mapping is probably wrong) — and reports an honest null
when there was no ontology to check against."""

from kg_contracts.registry import Backend, GraphDescriptor
from kg_contracts.testing.factories import make_attribute_candidate, make_entity_candidate
from kgis.ontology import CoverageCounter, Ontology, OntologyCoverage


def counter_over(*entity_types: str) -> CoverageCounter:
    counter = CoverageCounter()
    for index, entity_type in enumerate(entity_types):
        counter.observe(make_entity_candidate(entity_type=entity_type, key=f"e{index}"))
    return counter


class TestOntology:
    def test_empty_term_set_is_unconstrained_not_forbidden(self) -> None:
        ontology = Ontology(version="1")
        assert ontology.declares_entity_type("Anything") is True
        assert ontology.declares_relation_type("ANYTHING") is True
        assert ontology.declares_attribute("anything") is True

    def test_declared_terms_are_enforced(self) -> None:
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        assert ontology.declares_entity_type("Player") is True
        assert ontology.declares_entity_type("Coach") is False

    def test_from_descriptor_reads_node_and_edge_types(self) -> None:
        descriptor = GraphDescriptor(
            name="baseball",
            owner="djjay",
            domain="sport",
            backend=Backend.MEMORY,
            created_by="test",
            node_types=("Player", "Team"),
            edge_types=("PLAYS_FOR",),
            ontology_version="3",
        )
        ontology = Ontology.from_descriptor(descriptor)
        assert ontology.entity_types == frozenset({"Player", "Team"})
        assert ontology.relation_types == frozenset({"PLAYS_FOR"})
        assert ontology.version == "3"

    def test_from_descriptor_leaves_attributes_unconstrained(self) -> None:
        """GraphDescriptor has no attribute vocabulary — a real registry gap, flagged as an ADR."""
        descriptor = GraphDescriptor(
            name="g", owner="o", domain="d", backend=Backend.MEMORY, created_by="t"
        )
        assert Ontology.from_descriptor(descriptor).attributes == frozenset()

    def test_from_descriptor_without_a_version_says_unversioned(self) -> None:
        descriptor = GraphDescriptor(
            name="g", owner="o", domain="d", backend=Backend.MEMORY, created_by="t"
        )
        assert Ontology.from_descriptor(descriptor).version == "unversioned"


class TestCoverageCounter:
    def test_counts_terms_by_candidate_kind(self) -> None:
        counter = CoverageCounter()
        counter.observe(make_entity_candidate(entity_type="Player", key="a"))
        counter.observe(make_entity_candidate(entity_type="Player", key="b"))
        counter.observe(make_attribute_candidate(attribute="height_cm"))
        coverage = counter.summarize(None)
        assert coverage.entity_types == {"Player": 2}
        assert coverage.attributes == {"height_cm": 1}

    def test_unknown_terms_are_reported(self) -> None:
        """Spec §6: unknown types reported, never hidden."""
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        coverage = counter_over("Player", "Coach").summarize(ontology)
        assert coverage.unknown_entity_types == ("Coach",)
        assert coverage.has_unknown_terms is True

    def test_unused_declared_terms_are_reported(self) -> None:
        """A Player ontology whose ingest produced zero Players is a mapping bug."""
        ontology = Ontology(version="1", entity_types=frozenset({"Player", "Team"}))
        coverage = counter_over("Player").summarize(ontology)
        assert coverage.unused_entity_types == ("Team",)

    def test_terms_are_sorted_for_determinism(self) -> None:
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        coverage = counter_over("Zebra", "Aardvark").summarize(ontology)
        assert coverage.unknown_entity_types == ("Aardvark", "Zebra")

    def test_no_ontology_reports_an_honest_null_not_a_reassuring_hundred_percent(self) -> None:
        """ADR-0009: "nothing was checkable" and "everything is known" are different results."""
        coverage = counter_over("Player").summarize(None)
        assert coverage.declared is False
        assert coverage.coverage_ratio is None
        assert coverage.unknown_entity_types == ()

    def test_coverage_ratio_measures_declared_terms_actually_produced(self) -> None:
        ontology = Ontology(
            version="1", entity_types=frozenset({"Player", "Team", "Coach", "Venue"})
        )
        coverage = counter_over("Player", "Team").summarize(ontology)
        assert coverage.coverage_ratio == 0.5

    def test_full_coverage_is_one(self) -> None:
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        assert counter_over("Player").summarize(ontology).coverage_ratio == 1.0

    def test_unknown_terms_do_not_inflate_coverage(self) -> None:
        """Producing junk terms must not look like covering the ontology."""
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        coverage = counter_over("Coach", "Umpire").summarize(ontology)
        assert coverage.coverage_ratio == 0.0

    def test_a_graph_declaring_no_terms_has_no_coverage_to_measure(self) -> None:
        """Regression: deriving the declared set from the used/unused fields made an
        unconstrained ontology (declared nothing) indistinguishable from a fully
        covered one, and reported 100% coverage for a graph with no vocabulary."""
        assert counter_over("Player").summarize(Ontology(version="1")).coverage_ratio is None

    def test_coverage_reports_the_declared_vocabulary_it_measured_against(self) -> None:
        ontology = Ontology(
            version="1",
            entity_types=frozenset({"Team", "Player"}),
            relation_types=frozenset({"PLAYS_FOR"}),
        )
        coverage = counter_over("Player").summarize(ontology)
        assert coverage.declared_entity_types == ("Player", "Team")
        assert coverage.declared_relation_types == ("PLAYS_FOR",)

    def test_declared_attributes_count_toward_coverage(self) -> None:
        ontology = Ontology(version="1", attributes=frozenset({"height_cm", "weight_kg"}))
        counter = CoverageCounter()
        counter.observe(make_attribute_candidate(attribute="height_cm"))
        assert counter.summarize(ontology).coverage_ratio == 0.5

    def test_empty_run_against_a_declared_ontology_covers_nothing(self) -> None:
        ontology = Ontology(version="1", entity_types=frozenset({"Player"}))
        coverage = CoverageCounter().summarize(ontology)
        assert coverage.coverage_ratio == 0.0
        assert coverage.unused_entity_types == ("Player",)

    def test_spec_level_kinds_are_counted_nowhere_rather_than_forced_into_a_bucket(self) -> None:
        coverage: OntologyCoverage = CoverageCounter().summarize(None)
        assert coverage.entity_types == {}
        assert coverage.relation_types == {}
        assert coverage.attributes == {}
