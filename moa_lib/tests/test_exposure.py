"""Tests for moa_lib.exposure (design §4.4, §8.2 B3/B6).

Every test here is paired with a NEGATIVE CONTROL: a case that must come out the
other way, so a test that always passes cannot hide. Where a negative control
cannot be expressed as an input, the test asserts on a value that changes when the
behaviour is broken (e.g. the exact tier, not merely "not None").
"""
import pytest

from moa_lib import exposure as ex
from moa_lib.evidence_schema import Tier

# --------------------------------------------------------------------------- #
# vocabularies
# --------------------------------------------------------------------------- #


def test_modality_and_route_vocabularies_are_the_designed_ones():
    assert {m.value for m in ex.Modality} == {
        "small_molecule", "peptide", "protein_antibody", "oligonucleotide",
        "herbal_formula", "extracellular_vesicle", "cell", "other"}
    assert {r.value for r in ex.Route} == {
        "oral", "topical_skin", "transdermal", "subcutaneous", "intramuscular",
        "intravenous", "inhaled", "intranasal", "ophthalmic", "otic",
        "buccal_sublingual", "rectal", "vaginal", "intra_articular", "intrathecal",
        "other"}


def test_route_normalisation_maps_v11_strings_and_refuses_to_guess():
    assert ex.normalize_route("topical") is ex.Route.TOPICAL_SKIN
    assert ex.normalize_route("oral") is ex.Route.ORAL
    assert ex.normalize_route("外用") is ex.Route.TOPICAL_SKIN
    assert ex.normalize_route("SC") is ex.Route.SUBCUTANEOUS
    # negative control: an unknown route must NOT be mapped onto a plausible one
    assert ex.normalize_route("intraperitoneal") is ex.Route.OTHER
    assert ex.normalize_route("by telepathy") is ex.Route.OTHER


def test_formulation_is_independent_of_route_and_free_text_is_kept():
    assert ex.normalize_formulation("Ointment") == ("ointment", True)
    assert ex.normalize_formulation("microneedle") == ("microneedle", True)
    # free text allowed, flagged as uncontrolled, never dropped
    value, in_vocab = ex.normalize_formulation("bespoke water-in-oil mask base")
    assert value == "bespoke water-in-oil mask base"
    assert in_vocab is False
    # route and formulation are independent inputs: same route, two formulations
    plain = ex.build_profile(ex.Modality.PEPTIDE, ex.Route.SUBCUTANEOUS, "solution")
    depot = ex.build_profile(ex.Modality.PEPTIDE, ex.Route.SUBCUTANEOUS, "depot")
    assert plain.formulation == "solution" and depot.formulation == "depot"
    assert plain.route == depot.route == "subcutaneous"


# --------------------------------------------------------------------------- #
# source priority and tiers (design §4.4)
# --------------------------------------------------------------------------- #


def test_source_priority_label_beats_chembl_beats_pk_beats_rule_of_thumb():
    obs = [
        ex.Observation("systemic", "none", ex.rule_of_thumb_source("default")),
        ex.Observation("systemic", "low", ex.published_pk_source("PMID:1")),
        ex.Observation("systemic", "full", ex.label_source("DailyMed SPL x")),
        ex.Observation("systemic", "low", ex.chembl_flag_source("CHEMBL25")),
    ]
    p = ex.build_profile(ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, observations=obs)
    assert p.systemic == "full"
    assert p.source_of("systemic").kind == "label"
    assert p.tier_of("systemic") is Tier.E0
    # negative control: drop the label and the ChEMBL flag must win over published PK
    p2 = ex.build_profile(ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, observations=obs[:2] + obs[3:])
    assert p2.source_of("systemic").kind == "chembl_flag"
    assert p2.tier_of("systemic") is Tier.E2
    # ... and with neither, published PK wins over the rule of thumb
    p3 = ex.build_profile(ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, observations=obs[:2])
    assert p3.source_of("systemic").kind == "published_pk"
    assert p3.tier_of("systemic") is Tier.E1


def test_source_kinds_carry_the_designed_tiers():
    assert ex.label_source("x").tier is Tier.E0
    assert ex.chembl_flag_source("x").tier is Tier.E2
    assert ex.published_pk_source("x").tier is Tier.E1
    assert ex.classical_source("x").tier is Tier.E1
    assert ex.rule_of_thumb_source().tier is Tier.E4
    # negative control: a rule of thumb must never be anything but E4
    assert ex.rule_of_thumb_source("very convincing").tier is not Tier.E1


def test_unknown_source_kind_and_bad_values_are_refused():
    with pytest.raises(ValueError):
        ex.FieldSource("my_intuition", "x")
    with pytest.raises(ValueError):
        ex.Observation("systemic", "quite a lot", ex.label_source("x"))
    with pytest.raises(ValueError):
        ex.Observation("primary_compartments", ["pancreas_islet"], ex.label_source("x"))
    with pytest.raises(ValueError):
        ex.Observation("bioavailability", 0.4, ex.label_source("x"))


# --------------------------------------------------------------------------- #
# B6 — a rule-of-thumb-only profile is provisional and carries no systemic claim
# --------------------------------------------------------------------------- #


def test_rule_of_thumb_only_profile_is_provisional_and_blocks_systemic_claims():
    """Design §8.2 B6: an E4 default cannot alone support a systemic or responder claim."""
    p = ex.build_profile(ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, "tablet",
                         compound="unsourced-compound")
    assert p.systemic == "full"                      # the route default says full...
    assert p.tier_of("systemic") is Tier.E4          # ... on an E4 rule of thumb
    assert p.provisional is True
    assert "systemic" in p.provisional_fields

    ok, why = p.supports_systemic_claim()
    assert ok is False
    assert "rule-of-thumb" in why and "E4" in why

    ok_r, why_r = p.supports_responder_claim()
    assert ok_r is False
    assert "responder" in why_r.lower()


def test_a_sourced_full_systemic_profile_does_support_the_claim():
    """Negative control for the test above: the gate must be able to say YES, or it
    is just an unconditional refusal."""
    p = ex.build_profile(
        ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, "tablet", compound="atorvastatin",
        observations=[ex.Observation(
            "systemic", "full",
            ex.label_source("DailyMed SPL a60cc18b-0631-4cf0-b021-9f52224ece65",
                            "LIPITOR tablets"))])
    assert p.provisional is False or "systemic" not in p.provisional_fields
    ok, why = p.supports_systemic_claim()
    assert ok is True
    assert "label" in why
    assert p.supports_responder_claim()[0] is True


def test_low_systemic_exposure_is_not_a_systemic_claim():
    """A topical label's 'minimal absorption' is not licence for systemic efficacy."""
    p = ex.build_profile(
        ex.Modality.SMALL_MOLECULE, ex.Route.TOPICAL_SKIN, "cream", compound="ruxolitinib",
        observations=[ex.Observation("systemic", "low",
                                     ex.label_source("DailyMed SPL 24da5509", "OPZELURA cream"))])
    ok, why = p.supports_systemic_claim()
    assert ok is False and "LOW" in why
    assert p.supports_responder_claim()[0] is False


# --------------------------------------------------------------------------- #
# B6 — herbal formula: formula-level route is E1 and propagates; systemic stays provisional
# --------------------------------------------------------------------------- #


def test_herbal_formula_level_route_is_E1_and_propagates_to_constituents():
    formula = ex.herbal_formula_profile(
        "七白散 (Qibai San)", "topical",
        "太平聖惠方 (七白膏); 永類鈐方 (洗面七白散) — 外用美白祛斑",
        formulation="mask")
    # formula level: compartment from the classical source = E1
    assert formula.tier_of("primary_compartments") is Tier.E1
    assert formula.source_of("primary_compartments").kind == "classical_source"
    assert "skin_epidermis" in formula.primary_compartments
    # ... but the formula's systemic exposure is NOT asserted from that source
    assert formula.tier_of("systemic") is Tier.E4
    assert formula.provisional is True

    # propagation: the constituent inherits the compartment AT E1
    con = ex.constituent_profile(formula, "imperatorin")
    assert con.tier_of("primary_compartments") is Tier.E1
    assert con.source_of("primary_compartments").kind == "classical_source"
    assert con.primary_compartments == formula.primary_compartments
    # ... and its systemic exposure stays provisional (E4) -> no systemic claim
    assert con.tier_of("systemic") is Tier.E4
    assert "systemic" in con.provisional_fields
    assert con.supports_systemic_claim()[0] is False


def test_constituent_with_its_own_PK_stops_being_provisional_for_systemic():
    """Negative control: the provisional flag must lift when the constituent has
    its own PK, otherwise the previous test proves nothing about the mechanism."""
    formula = ex.herbal_formula_profile("Test Decoction", "oral", "《中國藥典》 2020 — 內服")
    con = ex.constituent_profile(
        formula, "well-studied-constituent",
        own_pk=ex.Observation("systemic", "full",
                              ex.published_pk_source("PMID:99999999",
                                                     "oral bioavailability measured in humans")))
    assert con.tier_of("primary_compartments") is Tier.E1      # still inherited
    assert con.tier_of("systemic") is Tier.E1                  # now its own PK
    assert "systemic" not in con.provisional_fields
    assert con.supports_systemic_claim()[0] is True


def test_an_unsourced_herbal_route_is_refused():
    """A formula-level route is E1 only BECAUSE it is cited; without the citation it
    must not be constructible at all."""
    with pytest.raises(ValueError):
        ex.herbal_formula_profile("Mystery Powder", "oral", "")


# --------------------------------------------------------------------------- #
# B3 — target-tissue reachability
# --------------------------------------------------------------------------- #


def _topical_label_profile(compound="ruxolitinib"):
    return ex.build_profile(
        ex.Modality.SMALL_MOLECULE, ex.Route.TOPICAL_SKIN, "cream", compound=compound,
        observations=[ex.Observation(
            "systemic", "low",
            ex.label_source("DailyMed SPL 24da5509-6631-4795-9d42-273faecd08e7",
                            "OPZELURA cream — label route + clinical pharmacology"))])


def test_topical_route_against_marrow_pathology_is_not_deliverable_to_target_tissue():
    """Design §8.2 B3 / panel case 12: ruxolitinib CREAM against myelofibrosis must
    stop at Step 0, not run to Step 5."""
    prof = _topical_label_profile()
    r = ex.reaches_target_tissue(prof, "bone marrow")
    assert r.verdict == ex.NOT_DELIVERABLE_TO_TARGET_TISSUE
    assert r.reachable is False
    assert r.target_compartment == "bone_marrow"
    mismatch, r2 = ex.exposure_mismatch(prof, "bone marrow")
    assert mismatch is True
    assert r2.is_mismatch is True
    # the stop report must be able to name route, compartments, tissue and sources
    assert r2.route_compartments and r2.sources and r2.rationale


def test_the_same_profile_reaches_its_own_tissue():
    """Negative control: if every tissue came back not_deliverable the gate would be
    useless."""
    prof = _topical_label_profile()
    for tissue in ("lesional skin", "epidermis", "keratinocytes", "dermis"):
        r = ex.reaches_target_tissue(prof, tissue)
        assert r.verdict == ex.REACHABLE_DIRECT, tissue
        assert r.reachable is True
        assert r.via == "direct"
    mismatch, _ = ex.exposure_mismatch(prof, "lesional skin")
    assert mismatch is False


def test_systemic_route_reaches_a_perfused_distal_tissue():
    oral = ex.build_profile(
        ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, "tablet", compound="atorvastatin",
        observations=[ex.Observation("systemic", "full",
                                     ex.label_source("DailyMed SPL a60cc18b", "LIPITOR"))])
    # the liver is a FIRST-PASS compartment of the oral route, so it is direct
    assert ex.reaches_target_tissue(oral, "liver").verdict == ex.REACHABLE_DIRECT
    # a distal perfused tissue is reached via the circulation
    r = ex.reaches_target_tissue(oral, "bone marrow")
    assert r.verdict == ex.REACHABLE_SYSTEMIC
    assert r.via == "systemic" and r.reachable is True
    assert r.provisional is False
    # negative control: a luminal compartment is NOT reached from the circulation
    skin_surface = ex.reaches_target_tissue(oral, "skin surface")
    assert skin_surface.verdict == ex.NOT_DELIVERABLE_TO_TARGET_TISSUE


def test_low_systemic_exposure_does_not_reach_a_distal_tissue():
    """'Low' is incidental absorption, not delivery. Without this rule a cream
    analysed against a marrow disease would pass."""
    low = ex.build_profile(
        ex.Modality.SMALL_MOLECULE, ex.Route.INHALED, "dpi", compound="tiotropium",
        observations=[ex.Observation("systemic", "low",
                                     ex.label_source("DailyMed SPL 820839ef", "SPIRIVA"))])
    assert ex.reaches_target_tissue(low, "bone marrow").verdict == \
        ex.NOT_DELIVERABLE_TO_TARGET_TISSUE
    # negative control: the same route DOES reach its own compartment
    assert ex.reaches_target_tissue(low, "airway").verdict == ex.REACHABLE_DIRECT
    assert ex.reaches_target_tissue(low, "lung").verdict == ex.REACHABLE_DIRECT


def test_cns_and_ocular_compartments_need_their_own_evidence():
    oral_full = ex.build_profile(
        ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, "tablet",
        observations=[ex.Observation("systemic", "full", ex.label_source("SPL x")),
                      ex.Observation("cns", "unlikely", ex.published_pk_source("PMID:2"))])
    r = ex.reaches_target_tissue(oral_full, "brain")
    assert r.verdict == ex.NOT_DELIVERABLE_TO_TARGET_TISSUE
    assert ex.reaches_target_tissue(oral_full, "retina").verdict == \
        ex.NOT_DELIVERABLE_TO_TARGET_TISSUE
    # negative control: sourced CNS access makes the brain reachable
    cns_ok = ex.build_profile(
        ex.Modality.SMALL_MOLECULE, ex.Route.ORAL, "tablet",
        observations=[ex.Observation("systemic", "full", ex.label_source("SPL x")),
                      ex.Observation("cns", "yes",
                                     ex.published_pk_source("PMID:3", "CSF:plasma ratio"))])
    assert ex.reaches_target_tissue(cns_ok, "brain").verdict == ex.REACHABLE_SYSTEMIC
    # and an intrathecal route reaches the CSF directly
    it = ex.build_profile(ex.Modality.OLIGONUCLEOTIDE, ex.Route.INTRATHECAL, "solution")
    assert ex.reaches_target_tissue(it, "cerebrospinal fluid").verdict == ex.REACHABLE_DIRECT


def test_an_unmappable_tissue_is_not_assessable_never_a_pass():
    prof = _topical_label_profile()
    unmappable = "qi stagnation of the san jiao"
    r = ex.reaches_target_tissue(prof, unmappable)
    assert r.verdict == ex.NOT_ASSESSABLE
    assert r.reachable is False
    assert r.target_compartment is None
    # not_assessable must NOT raise EXPOSURE_MISMATCH either — it is a separate state
    mismatch, _ = ex.exposure_mismatch(prof, unmappable)
    assert mismatch is False
    # negative control: a mappable tissue resolves
    assert ex.resolve_compartment("bone marrow") == "bone_marrow"
    assert ex.resolve_compartment("nonsense tissue") is None


def test_tissue_synonyms_match_only_at_word_boundaries():
    """A bare substring match would read 'foreskin' as skin, which is how a wrong
    compartment gets into a run unnoticed."""
    assert ex.resolve_compartment("lesional skin") == "skin_epidermis"
    assert ex.resolve_compartment("foreskin") is None
    assert ex.resolve_compartment("spleen-meridian") == "lymphoid_tissue"   # real word match
    assert ex.resolve_compartment("years of symptoms") is None              # not 'ear'
    assert ex.resolve_compartment("colonisation") is None                   # not 'colon'


def test_compartment_vocabulary_is_partitioned_by_barrier_behaviour():
    assert ex.LUMINAL_COMPARTMENTS & ex.PERFUSED_COMPARTMENTS == frozenset()
    assert ex.LUMINAL_COMPARTMENTS & ex.BARRIER_RESTRICTED_COMPARTMENTS == frozenset()
    assert ex.PERFUSED_COMPARTMENTS & ex.BARRIER_RESTRICTED_COMPARTMENTS == frozenset()
    # every default route compartment is in the vocabulary
    for route, (comps, systemic, cns) in ex.ROUTE_DEFAULTS.items():
        assert set(comps) <= ex.COMPARTMENTS, route
        assert systemic in ex.SYSTEMIC_LEVELS and cns in ex.CNS_LEVELS


def test_macromolecule_by_mouth_defaults_to_no_systemic_exposure():
    p = ex.build_profile(ex.Modality.PEPTIDE, ex.Route.ORAL, "tablet")
    assert p.systemic == "none"
    assert p.supports_systemic_claim()[0] is False
    # negative control: a small molecule by the same route defaults to full
    assert ex.build_profile(ex.Modality.SMALL_MOLECULE, ex.Route.ORAL).systemic == "full"


def test_profile_serialises_with_its_tiers_for_the_run_card():
    p = _topical_label_profile()
    d = p.to_dict()
    assert d["route"] == "topical_skin" and d["formulation"] == "cream"
    assert d["tiers"]["systemic"] == "E0"
    assert d["field_sources"]["systemic"]["kind"] == "label"
    assert d["provisional"] is True              # compartments still E4 here
    assert "primary_compartments" in d["provisional_fields"]
