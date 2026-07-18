"""The report's job is to never lie: distinct counters for distinct rejection
causes, honest absence of stages KGIS does not own, and a fingerprint that is
equal across replays but excludes wall-clock time."""

from kg_contracts.candidates import SourceCoordinates
from kg_contracts.curation import FailureKind, ValidationDecision
from kg_contracts.ingestion import IngestReport
from kg_contracts.stores import SubmissionOutcome, SubmissionStatus
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ontology import OntologyCoverage
from kgis.report import DryRunPlan, IngestionReport, IngestWarning
from kgis.validate import RecordValidation

COORDS = SourceCoordinates(source_type="csv", locator="p.csv", fragment="row=2")


def report(**overrides: object) -> IngestionReport:
    defaults: dict[str, object] = {
        "graph_id": "baseball",
        "job_id": "job-1",
        "producer_run_id": "run-1",
        "mode": "execute",
        "source_type": "csv",
        "source_locator": "players.csv",
    }
    return IngestionReport(**{**defaults, **overrides})  # type: ignore[arg-type]


def record_failure(index: int = 0) -> RecordValidation:
    return RecordValidation(
        index=index,
        coordinates=COORDS,
        valid=False,
        failure_kind=FailureKind.BAD_DATA,
        reasons=("coercion_failed: bad",),
    )


class TestIsAnIngestReport:
    def test_an_ingestion_report_is_a_contract_ingest_report(self) -> None:
        """It must be usable anywhere the contract type is expected."""
        assert isinstance(report(), IngestReport)

    def test_inherits_the_contract_record_accumulator(self) -> None:
        r = report()
        r.record(SubmissionOutcome(candidate_id="c1", status=SubmissionStatus.RECEIVED, trace_id="t"))
        r.record(SubmissionOutcome(candidate_id="c2", status=SubmissionStatus.DUPLICATE, trace_id="t"))
        assert r.received == 1
        assert r.duplicates == 1

    def test_inherits_the_contract_fail_method(self) -> None:
        r = report()
        r.fail("reader exploded")
        assert r.incomplete is True
        assert r.failures == ["reader exploded"]


class TestCountersAreDistinct:
    def test_records_invalid_is_not_the_inherited_sink_invalid(self) -> None:
        """Rows we rejected vs candidates the sink rejected — opposite meanings."""
        r = report()
        r.note_validation_failure(record_failure())
        r.record(SubmissionOutcome(candidate_id="c", status=SubmissionStatus.INVALID, trace_id="t"))
        assert r.records_invalid == 1  # our rejection
        assert r.invalid == 1  # the sink's rejection

    def test_suppressed_is_not_the_inherited_ledger_duplicates(self) -> None:
        """Intra-run duplicate keys vs candidates the ledger already had."""
        r = report(candidates_suppressed=3)
        r.record(SubmissionOutcome(candidate_id="c", status=SubmissionStatus.DUPLICATE, trace_id="t"))
        assert r.candidates_suppressed == 3  # dropped before submission
        assert r.duplicates == 1  # ledger already had it


class TestAccumulators:
    def test_note_validation_failure_tallies_and_stores(self) -> None:
        r = report()
        failure = record_failure(index=7)
        r.note_validation_failure(failure)
        assert r.records_invalid == 1
        assert r.validation_failures == [failure]

    def test_note_candidate_rejection_tallies_and_stores(self) -> None:
        r = report()
        decision = ValidationDecision(
            candidate_id="cand_x",
            valid=False,
            failure_kind=FailureKind.UNSUPPORTED_ONTOLOGY,
            reasons=("unknown type",),
            policy_version="1",
            trace_id="t",
        )
        r.note_candidate_rejection(decision)
        assert r.candidates_rejected == 1
        assert r.candidate_rejections == [decision]

    def test_warn_records_a_structured_warning(self) -> None:
        r = report()
        r.warn("assumed_utc", "no tz on row 2", record_index=2, locator="players.csv")
        assert r.warnings == [
            IngestWarning(
                code="assumed_utc", message="no tz on row 2", record_index=2, locator="players.csv"
            )
        ]


class TestSucceededIsStrict:
    def test_a_clean_complete_run_succeeded(self) -> None:
        assert report().succeeded is True

    def test_a_run_with_a_rejected_record_did_not_succeed(self) -> None:
        """Spec §9: partial success is not success — that is how bad ingests ship."""
        r = report()
        r.note_validation_failure(record_failure())
        assert r.succeeded is False

    def test_a_run_with_a_rejected_candidate_did_not_succeed(self) -> None:
        r = report(candidates_rejected=1)
        assert r.succeeded is False

    def test_an_incomplete_run_did_not_succeed(self) -> None:
        r = report()
        r.fail("reader died")
        assert r.succeeded is False


class TestHonestAbsence:
    def test_stages_kgis_does_not_own_are_absent_not_zero(self) -> None:
        """"accepted=0" would claim nothing was accepted; absence says it is not ours to know."""
        fields = set(report().model_dump().keys())
        for downstream in ("identity_resolved", "accepted", "materialized", "indexed"):
            assert downstream not in fields

    def test_coverage_defaults_to_an_undeclared_honest_null(self) -> None:
        assert report().coverage == OntologyCoverage()
        assert report().coverage.coverage_ratio is None


class TestFingerprint:
    def test_two_reports_with_the_same_outcome_fingerprint_equally(self) -> None:
        assert report().fingerprint() == report().fingerprint()

    def test_fingerprint_excludes_wall_clock_time(self) -> None:
        """Elapsed time is the one field a replay may legitimately differ on."""
        fast = report(elapsed_seconds=0.1)
        slow = report(elapsed_seconds=99.0)
        assert fast.fingerprint() == slow.fingerprint()

    def test_fingerprint_reflects_a_real_difference(self) -> None:
        assert report(records_read=5).fingerprint() != report(records_read=6).fingerprint()

    def test_fingerprint_has_no_elapsed_key(self) -> None:
        assert "elapsed_seconds" not in report().fingerprint()


class TestDryRunPlan:
    def test_ledger_duplicates_none_is_an_honest_null(self) -> None:
        """No LedgerReader injected means we genuinely do not know — not zero."""
        plan = DryRunPlan(would_submit=3)
        assert plan.ledger_duplicates is None
        assert plan.ledger_checked is False

    def test_ledger_checked_when_a_count_is_present(self) -> None:
        plan = DryRunPlan(would_submit=3, ledger_duplicates=1)
        assert plan.ledger_checked is True

    def test_truncated_flag_separates_retained_list_from_true_counts(self) -> None:
        """A cap on the retained candidates must never look like a small plan."""
        plan = DryRunPlan(would_submit=10_000, candidates=(make_entity_candidate(),), truncated=True)
        assert plan.would_submit == 10_000
        assert len(plan.candidates) == 1
        assert plan.truncated is True


class TestSummary:
    def test_summary_leads_with_mode_and_core_counts(self) -> None:
        line = report(records_read=3, records_valid=3, candidates_built=3).summary()
        assert line.startswith("execute read=3 valid=3 invalid=0 built=3")

    def test_summary_flags_incomplete_runs(self) -> None:
        r = report()
        r.fail("boom")
        assert "INCOMPLETE" in r.summary()

    def test_dry_run_summary_reports_would_submit(self) -> None:
        r = report(mode="dry_run", plan=DryRunPlan(would_submit=5))
        assert "would_submit=5" in r.summary()
