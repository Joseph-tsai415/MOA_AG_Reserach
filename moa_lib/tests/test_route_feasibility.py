"""Tests for moa_lib.route_feasibility (design §4.5, §8.2 B4).

Two jobs:
  1. the v11 compatibility layer must give the SAME answers it gave before the
     refactor, because shipped v11 run scripts call it;
  2. the v12 three levels, keyed rule sets, approved-product precedence and the
     "precedent at E1+ or it is not_deliverable" rule must behave as designed.

Every behaviour has a NEGATIVE CONTROL — a case that must come out the other way —
so no assertion here can pass unconditionally.
"""
import pytest

from moa_lib import route_feasibility as rf
from moa_lib.evidence_schema import Tier
from moa_lib.exposure import Modality, Route

# the compounds in the v11 module's own __main__ block
PACHYMIC_ACID = {"name": "Pachymic acid", "mw": 528.8, "logp": 7.2, "hbd": 2, "hba": 5}
MILITARINE = {"name": "Militarine", "mw": 726.7, "logp": -0.5, "hbd": 9, "hba": 17}
IMPERATORIN = {"name": "Imperatorin", "mw": 270.28, "logp": 3.4, "hbd": 0, "hba": 4}
V11_COMPOUNDS = [PACHYMIC_ACID, MILITARINE, IMPERATORIN]


# =========================================================================== #
# 1. v11 compatibility layer — frozen behaviour
# =========================================================================== #


def test_v11_topical_verdicts_are_unchanged():
    """The exact answers the v11 __main__ block printed."""
    t = rf.screen(V11_COMPOUNDS, "topical")
    assert t["Pachymic acid"].feasible is False
    assert t["Militarine"].feasible is False
    assert t["Imperatorin"].feasible is True
    # and the exact violation strings, which run reports render verbatim
    assert t["Pachymic acid"].violations == [
        "MW 529 > 500 (poor stratum-corneum permeation)",
        "LogP 7.2 > 4 (too lipophilic — stays in stratum corneum, poor flux)"]
    assert t["Militarine"].violations == [
        "MW 727 > 500 (poor stratum-corneum permeation)",
        "LogP -0.5 < 1 (too polar to partition into skin lipids)"]
    assert t["Imperatorin"].violations == []
    assert t["Imperatorin"].note == "within topical permeation window"
    assert t["Militarine"].note == "permeation window MW<=500, LogP~1-3"
    assert t["Imperatorin"].route == "topical"


def test_v11_oral_verdicts_are_unchanged():
    o = rf.screen(V11_COMPOUNDS, "oral")
    assert o["Pachymic acid"].feasible is False
    assert o["Militarine"].feasible is False
    assert o["Imperatorin"].feasible is True
    assert o["Pachymic acid"].violations == ["MW 529 > 500", "LogP 7.2 > 5"]
    assert o["Militarine"].violations == ["MW 727 > 500", "HBD 9 > 5", "HBA 17 > 10"]
    assert o["Imperatorin"].note == "Lipinski Ro5"
    assert o["Militarine"].note == "Lipinski Ro5 (>=2 violations → poor oral bioavailability)"
    assert o["Imperatorin"].route == "oral"


def test_v11_lipinski_still_allows_exactly_one_violation():
    """Negative control for the oral rule: one violation passes, two fail."""
    one = rf.oral_feasible(mw=600, logp=3, hbd=2, hba=5)
    assert one.feasible is True and len(one.violations) == 1
    two = rf.oral_feasible(mw=600, logp=6, hbd=2, hba=5)
    assert two.feasible is False and len(two.violations) == 2


def test_v11_missing_properties_still_say_cannot_assess():
    t = rf.topical_feasible(None, 2.0)
    assert t.feasible is False
    assert t.violations == ["missing MW/LogP"] and t.note == "cannot assess"
    o = rf.oral_feasible(300, 2.0, None, 5)
    assert o.feasible is False
    assert o.violations == ["missing property"] and o.note == "cannot assess"
    # ... and now also carry the v12 level for new consumers
    assert t.level == rf.Level.NOT_ASSESSABLE
    assert o.level == rf.Level.NOT_ASSESSABLE


def test_v11_unknown_route_still_passes_if_either_window_is_clear():
    u = rf.assess(IMPERATORIN, "unknown")
    assert u.route == "unknown" and u.feasible is True
    assert u.note == "feasible by at least one route" and u.violations == []
    # negative control: a compound failing both windows is still rejected
    both = rf.assess(MILITARINE, "unknown")
    assert both.feasible is False
    assert both.note == "delivery-implausible by BOTH topical and oral routes"
    assert both.violations  # the union of the two windows' violations


def test_v11_boundary_values_are_unchanged():
    assert rf.topical_feasible(500, 1).feasible is True        # inclusive bounds
    assert rf.topical_feasible(500.1, 1).feasible is False
    assert rf.topical_feasible(400, 0.999).feasible is False
    assert rf.topical_feasible(400, 4).feasible is True
    assert rf.topical_feasible(400, 4.0001).feasible is False
    assert rf.oral_feasible(500, 5, 5, 10).feasible is True    # zero violations
    assert rf.oral_feasible(500.1, 5.1, 5, 10).feasible is False


def test_v11_level_is_derived_but_feasible_is_authoritative_for_old_callers():
    """The compat layer must not reinterpret a v11 verdict through v12 levels."""
    f = rf.topical_feasible(804, 2.7)         # tacrolimus properties, v11 API
    assert f.feasible is False                # v11 said infeasible; it still does
    assert f.level == rf.Level.NOT_DELIVERABLE
    assert f.rule_set == "v11-compat:topical"
    # negative control: the v12 entry point, which DOES know the label, disagrees
    v12 = rf.assess_delivery({"name": "tacrolimus", "mw": 804, "logp": 2.7},
                             Route.TOPICAL_SKIN)
    assert v12.level == rf.Level.AS_IS


# =========================================================================== #
# 2. levels, rule sets and precedence
# =========================================================================== #


def test_four_levels_exist_and_only_as_is_is_feasible():
    assert {l.value for l in rf.Level} == {"as_is", "dds_enabled", "not_deliverable",
                                           "not_assessable"}
    assert rf.Feasibility(rf.Level.AS_IS).feasible is True
    for lvl in (rf.Level.DDS_ENABLED, rf.Level.NOT_DELIVERABLE, rf.Level.NOT_ASSESSABLE):
        assert rf.Feasibility(lvl).feasible is False


def test_tacrolimus_ointment_is_as_is_by_label_precedence_despite_mw_804():
    """Design §4.5's worked case: MW 804 breaks the 500 Da skin rule, and the
    approved product wins anyway — citing the label."""
    f = rf.assess_delivery({"name": "tacrolimus", "mw": 804.0, "logp": 2.7},
                           Route.TOPICAL_SKIN, Modality.SMALL_MOLECULE, "ointment")
    assert f.level == rf.Level.AS_IS
    assert f.feasible is True
    # the violation is still REPORTED, not hidden — the rule is overridden, not erased
    assert any("804" in v and "500" in v for v in f.violations)
    assert "rule_of_thumb_overridden_by_approved_product" in f.flags
    # the label is cited, at E0, and resolvable
    label = [c for c in f.sources if c.ref.startswith("DailyMed")]
    assert label and label[0].tier is Tier.E0
    assert "3b7f0fed-9046-4094-a131-29d560733e47" in label[0].ref
    assert "PROTOPIC" in f.note or "PROTOPIC" in label[0].text


def test_the_same_molecule_without_its_label_fails_the_rule():
    """Negative control for precedence: strip the precedent and MW 804 must fail,
    or the test above would pass for the wrong reason."""
    f = rf.assess_delivery({"name": "not-tacrolimus-at-all", "mw": 804.0, "logp": 2.7},
                           Route.TOPICAL_SKIN, Modality.SMALL_MOLECULE, "ointment")
    assert f.level == rf.Level.NOT_DELIVERABLE
    assert f.feasible is False
    assert any("804" in v for v in f.violations)


def test_molecule_name_matching_is_not_a_substring_test():
    """A name that merely CONTAINS a known molecule's name must not inherit its
    label; salt and dosage-form qualifiers must still match."""
    assert rf._name_matches("tacrolimus", "tacrolimus") is True
    assert rf._name_matches("tacrolimus", "Tacrolimus ointment") is True
    assert rf._name_matches("atorvastatin", "atorvastatin calcium") is True
    assert rf._name_matches("semaglutide", "oral semaglutide") is True
    assert rf._name_matches("tiotropium", "tiotropium bromide") is True
    # negative controls
    assert rf._name_matches("tacrolimus", "not-tacrolimus-at-all") is False
    assert rf._name_matches("tacrolimus", "pimecrolimus") is False
    assert rf._name_matches("semaglutide", "semaglutide-like peptide 7") is False
    assert rf._name_matches("tacrolimus", "") is False
    assert rf.find_precedents("tacrolimus-analogue-3", Route.TOPICAL_SKIN) == []
    assert rf.find_precedents("tacrolimus", Route.TOPICAL_SKIN)


def test_precedence_needs_the_right_route_not_just_the_right_molecule():
    """Tacrolimus is also an approved ORAL drug, but the topical label cannot
    license an ophthalmic claim here: precedence is (molecule, route)."""
    f = rf.assess_delivery({"name": "tacrolimus", "mw": 804.0, "logp": 2.7},
                           Route.OPHTHALMIC, Modality.SMALL_MOLECULE, "eye_drop")
    assert f.level != rf.Level.AS_IS
    assert f.level == rf.Level.NOT_DELIVERABLE


def test_oral_peptide_without_precedent_is_not_deliverable():
    """Design §8.2 B4: this is the case that keeps `not_deliverable` reachable."""
    f = rf.assess_delivery({"name": "NovelPeptide-1", "mw": 2500.0},
                           Route.ORAL, Modality.PEPTIDE, "capsule")
    assert f.level == rf.Level.NOT_DELIVERABLE
    assert f.feasible is False
    assert f.rule_set.startswith("peptide/oral")
    # DDS directions may still be listed — they are candidates, not a level
    assert f.dds_candidates
    assert all(d.provisional for d in f.dds_candidates)


def test_oral_semaglutide_is_dds_enabled_by_its_approved_product():
    """Design §4.5/§5 case 2: an approved product that IS the enabling delivery
    system gives dds_enabled, not as_is."""
    f = rf.assess_delivery({"name": "semaglutide", "mw": 4113.6},
                           Route.ORAL, Modality.PEPTIDE, "tablet")
    assert f.level == rf.Level.DDS_ENABLED
    assert f.feasible is False                 # dds_enabled is not "deliverable as is"
    assert f.delivery_dependent is True
    assert any("SNAC" in (d.dds_class or "") for d in f.dds_candidates)
    lic = [d for d in f.dds_candidates if not d.provisional]
    assert lic and lic[0].precedent.tier in (Tier.E0, Tier.E1)
    assert any("27f15fac" in c.ref for c in f.sources)


def test_a_supplied_published_precedent_also_licenses_dds_enabled():
    f = rf.assess_delivery(
        {"name": "NovelPeptide-1", "mw": 2500.0}, Route.ORAL, Modality.PEPTIDE,
        precedents=[rf.Precedent(
            Modality.PEPTIDE.value, Route.ORAL.value, "published_study",
            rf.CITE_BUCKLEY_SNAC, dds_class="co-formulated permeation enhancer (SNAC)",
            similar_molecule=True)])
    assert f.level == rf.Level.DDS_ENABLED
    assert "similar molecule" in f.note


def test_analogy_only_does_not_license_dds_enabled():
    """Design §8.2 B4: analogy is E4. It is recorded as speculative and the level
    stays not_deliverable."""
    f = rf.assess_delivery(
        {"name": "NovelPeptide-1", "mw": 2500.0}, Route.ORAL, Modality.PEPTIDE,
        precedents=[rf.analogy("a peptide of similar size is said to be absorbed",
                               Modality.PEPTIDE, Route.ORAL)])
    assert f.level == rf.Level.NOT_DELIVERABLE
    assert "analogy_only_not_sufficient" in f.flags
    assert "analogy is not a precedent" in f.note.lower()
    # the analogy is still on the record, not silently dropped
    assert any(p.kind == "analogy" and p.tier is Tier.E4 for p in f.precedents)


def test_an_e4_precedent_cannot_be_smuggled_in_as_a_published_study():
    """The gate is the TIER, not the label on the object."""
    sneaky = rf.Precedent(
        Modality.PEPTIDE.value, Route.ORAL.value, "published_study",
        rf.Citation("", "trust me", Tier.E4), dds_class="hand-waving")
    assert sneaky.licenses_dds is False
    f = rf.assess_delivery({"name": "NovelPeptide-1", "mw": 2500.0}, Route.ORAL,
                           Modality.PEPTIDE, precedents=[sneaky])
    assert f.level == rf.Level.NOT_DELIVERABLE
    # negative control: the same object at E1 does license it
    ok = rf.Precedent(Modality.PEPTIDE.value, Route.ORAL.value, "published_study",
                      rf.Citation("PMID:30429357", "real study", Tier.E1),
                      dds_class="permeation enhancer")
    assert ok.licenses_dds is True
    assert rf.assess_delivery({"name": "NovelPeptide-1", "mw": 2500.0}, Route.ORAL,
                              Modality.PEPTIDE, precedents=[ok]).level == rf.Level.DDS_ENABLED


def test_skin_failure_plus_supplied_precedent_becomes_dds_enabled():
    """A delivery-implausible constituent is a development path, not a dead end
    (design §1 failure 4, G4) — but only with precedent."""
    plain = rf.assess_delivery(PACHYMIC_ACID, Route.TOPICAL_SKIN)
    assert plain.level == rf.Level.NOT_DELIVERABLE
    assert plain.dds_candidates                      # directions are still offered
    with_pre = rf.assess_delivery(
        PACHYMIC_ACID, Route.TOPICAL_SKIN,
        precedents=[rf.Precedent(
            Modality.SMALL_MOLECULE.value, Route.TOPICAL_SKIN.value, "published_study",
            rf.CITE_NAIK_SKIN, dds_class="chemical permeation enhancer",
            similar_molecule=True)])
    assert with_pre.level == rf.Level.DDS_ENABLED
    assert with_pre.delivery_dependent is True


def test_parenteral_routes_skip_absorption_rules():
    """Design §4.5: absorption rules do not apply; as_is for systemic exposure."""
    for route in (Route.SUBCUTANEOUS, Route.INTRAMUSCULAR, Route.INTRAVENOUS):
        f = rf.assess_delivery({"name": "dupilumab"}, route, Modality.PROTEIN_ANTIBODY,
                               "prefilled_syringe")
        assert f.level == rf.Level.AS_IS, route
        assert f.violations == []
        assert "not applicable" in f.rule_set or "not applicable" in f.note
    # a 150 kDa antibody with no descriptors at all is still as_is by SC
    sc = rf.assess_delivery({"name": "dupilumab", "mw": 146900.0},
                            Route.SUBCUTANEOUS, Modality.PROTEIN_ANTIBODY)
    assert sc.level == rf.Level.AS_IS
    assert any("595f437d" in c.ref for c in sc.sources)      # label bioavailability noted
    # negative control: the SAME antibody by mouth is not deliverable
    oral = rf.assess_delivery({"name": "dupilumab", "mw": 146900.0}, Route.ORAL,
                              Modality.PROTEIN_ANTIBODY)
    assert oral.level == rf.Level.NOT_DELIVERABLE
    # ... and on the skin it fails the 500 Da rule
    skin = rf.assess_delivery({"name": "dupilumab", "mw": 146900.0, "logp": -2.0},
                              Route.TOPICAL_SKIN, Modality.PROTEIN_ANTIBODY)
    assert skin.level == rf.Level.NOT_DELIVERABLE


def test_inhaled_is_flag_only_not_a_molecular_pass_fail():
    f = rf.assess_delivery({"name": "some-inhaled-candidate", "mw": 900.0, "logp": 7.0},
                           Route.INHALED, Modality.SMALL_MOLECULE, "dpi")
    assert f.level == rf.Level.AS_IS
    assert f.violations == []
    assert any("device" in fl or "aerosol" in fl for fl in f.flags)
    assert any(c.ref == "PMID:14616418" for c in f.sources)
    # negative control: flag-only must not leak to other routes
    oral = rf.assess_delivery({"name": "some-inhaled-candidate", "mw": 900.0, "logp": 7.0,
                               "hbd": 1, "hba": 2}, Route.ORAL)
    assert oral.level == rf.Level.NOT_DELIVERABLE


def test_missing_descriptors_are_not_assessable_not_a_pass():
    f = rf.assess_delivery({"name": "mystery"}, Route.TOPICAL_SKIN)
    assert f.level == rf.Level.NOT_ASSESSABLE
    assert f.feasible is False
    assert "missing" in f.violations[0]
    # negative control: supply them and a verdict appears
    ok = rf.assess_delivery({"name": "mystery", "mw": 300, "logp": 2}, Route.TOPICAL_SKIN)
    assert ok.level == rf.Level.AS_IS


def test_unmapped_combinations_are_not_assessable_with_a_reason():
    """'Not in the table' must never be a silent pass OR a silent HALT
    (design §3 anti-goals)."""
    f = rf.assess_delivery({"name": "an-exosome-prep"}, Route.TOPICAL_SKIN,
                           Modality.EXTRACELLULAR_VESICLE)
    assert f.level == rf.Level.NOT_ASSESSABLE
    assert f.note
    rs, why = rf.resolve_rule_set(Modality.CELL, Route.OPHTHALMIC)
    assert rs is None and "no rule set" in why
    # a herbal formula is a mixture: assess constituents, not the formula
    rs2, why2 = rf.resolve_rule_set(Modality.HERBAL_FORMULA, Route.TOPICAL_SKIN)
    assert rs2 is None and "mixture" in why2
    formula = rf.assess_delivery({"name": "Qibai San"}, Route.TOPICAL_SKIN,
                                 Modality.HERBAL_FORMULA)
    assert formula.level == rf.Level.NOT_ASSESSABLE
    # an unresolved route is not assessable either
    assert rf.assess_delivery({"name": "x", "mw": 300, "logp": 2}, "intraperitoneal").level \
        == rf.Level.NOT_ASSESSABLE


def test_rule_sets_are_keyed_by_modality_and_route():
    assert rf.RULE_SETS[(Modality.SMALL_MOLECULE, Route.ORAL)] is rf.RS_ORAL_SMALL_MOLECULE
    assert rf.RULE_SETS[(Modality.SMALL_MOLECULE, Route.TOPICAL_SKIN)] is rf.RS_SKIN
    assert rf.RULE_SETS[(Modality.PROTEIN_ANTIBODY, Route.TOPICAL_SKIN)] is rf.RS_SKIN
    assert rf.RULE_SETS[(Modality.SMALL_MOLECULE, Route.INHALED)] is rf.RS_INHALED
    assert rf.RULE_SETS[(Modality.PEPTIDE, Route.ORAL)].kind == "precedent_required"
    assert rf.RULE_SETS[(Modality.SMALL_MOLECULE, Route.SUBCUTANEOUS)] is rf.RS_PARENTERAL
    # the same (modality, route) must not resolve to two different rule sets
    assert rf.resolve_rule_set("small molecule", "topical")[0] is rf.RS_SKIN


def test_oral_small_molecule_uses_lipinski_and_veber_and_fails_at_two():
    """Design §4.5: Ro5 + Veber (TPSA<=140, rotatable bonds<=10)."""
    good = rf.assess_delivery({"name": "imperatorin", "mw": 270.28, "logp": 3.4, "hbd": 0,
                               "hba": 4, "tpsa": 48.7, "rotatable_bonds": 3}, Route.ORAL)
    assert good.level == rf.Level.AS_IS and good.violations == []
    one = rf.assess_delivery({"name": "one-violation", "mw": 560, "logp": 3, "hbd": 2,
                              "hba": 5, "tpsa": 100, "rotatable_bonds": 4}, Route.ORAL)
    assert one.level == rf.Level.AS_IS and len(one.violations) == 1
    two = rf.assess_delivery({"name": "two-violations", "mw": 560, "logp": 3, "hbd": 2,
                              "hba": 5, "tpsa": 100, "rotatable_bonds": 14}, Route.ORAL)
    assert two.level == rf.Level.NOT_DELIVERABLE
    assert any("Veber" in v for v in two.violations)
    assert any("rotatable" in v for v in two.violations)
    # Veber descriptors are optional: absent, they simply are not tested
    no_veber = rf.assess_delivery({"name": "no-veber", "mw": 560, "logp": 3, "hbd": 2,
                                   "hba": 5}, Route.ORAL)
    assert no_veber.level == rf.Level.AS_IS


def test_atorvastatin_is_as_is_by_label_despite_two_rule_violations():
    """The precedence rule exists because real oral drugs break the rule of thumb."""
    props = {"name": "atorvastatin", "mw": 558.6, "logp": 5.0, "hbd": 4, "hba": 6,
             "tpsa": 112.0, "rotatable_bonds": 12}
    f = rf.assess_delivery(props, Route.ORAL)
    assert f.level == rf.Level.AS_IS
    assert len(f.violations) >= 2            # the rule of thumb would have failed it
    assert any("a60cc18b" in c.ref for c in f.sources)
    # negative control: the same descriptors under another name fail
    anon = dict(props, name="unknown-statin-like")
    assert rf.assess_delivery(anon, Route.ORAL).level == rf.Level.NOT_DELIVERABLE


# =========================================================================== #
# 3. citations: every threshold carries one, and provisional ones say so
# =========================================================================== #


def test_every_rule_set_carries_citations_and_flags_provisional_thresholds():
    for key, rs in rf.RULE_SETS.items():
        if rs.kind in ("descriptor", "flag_only", "not_applicable", "precedent_required"):
            assert rs.citations, f"{key} has no citation"
    # grounded thresholds
    assert rf.CITE_LIPINSKI.grounded and rf.CITE_LIPINSKI.ref == "PMID:11259830"
    assert rf.CITE_VEBER.grounded and rf.CITE_VEBER.ref == "PMID:12036371"
    assert rf.CITE_BOS_500DA.grounded and rf.CITE_BOS_500DA.ref == "PMID:10839713"
    assert rf.CITE_LABIRIS_LUNG.grounded and rf.CITE_BUCKLEY_SNAC.grounded
    # provisional thresholds must be marked, not quietly presented as cited
    assert rf.CITE_NAIK_SKIN.provisional and not rf.CITE_NAIK_SKIN.grounded
    assert rf.CITE_CORNEAL_WINDOW.provisional and rf.CITE_CORNEAL_WINDOW.tier is Tier.E4
    assert rf.RS_SKIN.provisional and rf.RS_OPHTHALMIC.provisional
    assert not rf.RS_ORAL_SMALL_MOLECULE.provisional


def test_provisional_thresholds_are_surfaced_in_the_result():
    f = rf.assess_delivery({"name": "too-polar", "mw": 300.0, "logp": -1.0},
                           Route.TOPICAL_SKIN)
    assert f.level == rf.Level.NOT_DELIVERABLE
    assert any("PROVISIONAL" in v for v in f.violations)
    assert f.provisional_rules                       # the citation objects
    # negative control: a grounded-only failure carries no provisional rule marker
    g = rf.assess_delivery({"name": "too-big", "mw": 900.0, "logp": 2.0, "hbd": 1,
                            "hba": 2, "tpsa": 50.0, "rotatable_bonds": 20}, Route.ORAL)
    assert g.level == rf.Level.NOT_DELIVERABLE
    assert g.provisional_rules == []


def test_every_registry_precedent_has_a_resolvable_identifier():
    for p in rf.PRODUCT_PRECEDENTS + rf.PUBLISHED_CLASS_PRECEDENTS:
        assert p.citation.ref, p
        assert p.citation.ref.startswith(("PMID:", "DOI:", "DailyMed SPL")), p.citation.ref
        assert p.citation.tier in (Tier.E0, Tier.E1), p
        assert p.licenses_dds, p
    # negative control: the analogy helper is explicitly NOT in that class
    a = rf.analogy("looks a bit like something that worked")
    assert a.citation.ref == "" and a.licenses_dds is False


def test_feasibility_serialises_for_the_run_card():
    f = rf.assess_delivery({"name": "semaglutide", "mw": 4113.6}, Route.ORAL, Modality.PEPTIDE)
    d = f.to_dict()
    assert d["level"] == "dds_enabled" and d["feasible"] is False
    assert d["route"] == "oral" and d["modality"] == "peptide"
    assert d["sources"] and d["dds_candidates"]
    assert d["dds_candidates"][0]["precedent"]["kind"] == "approved_product"


def test_screen_delivery_batches_the_v12_api():
    out = rf.screen_delivery(V11_COMPOUNDS, Route.TOPICAL_SKIN, Modality.SMALL_MOLECULE)
    assert set(out) == {"Pachymic acid", "Militarine", "Imperatorin"}
    assert out["Imperatorin"].level == rf.Level.AS_IS
    assert out["Pachymic acid"].level == rf.Level.NOT_DELIVERABLE
    assert out["Militarine"].level == rf.Level.NOT_DELIVERABLE


def test_exposure_profile_can_drive_the_assessment():
    from moa_lib import exposure as ex
    prof = ex.build_profile(ex.Modality.SMALL_MOLECULE, ex.Route.TOPICAL_SKIN, "ointment",
                            compound="tacrolimus")
    f = rf.assess_delivery({"name": "tacrolimus", "mw": 804.0, "logp": 2.7}, None, None,
                           exposure_profile=prof)
    assert f.route == "topical_skin" and f.modality == "small_molecule"
    assert f.level == rf.Level.AS_IS


def test_cns_target_with_a_non_penetrant_modality_is_flagged_not_failed():
    from moa_lib import exposure as ex
    prof = ex.build_profile(ex.Modality.PROTEIN_ANTIBODY, ex.Route.SUBCUTANEOUS, "solution")
    f = rf.assess_delivery({"name": "an-antibody"}, Route.SUBCUTANEOUS,
                           Modality.PROTEIN_ANTIBODY, exposure_profile=prof, cns_target=True)
    assert f.level == rf.Level.AS_IS                      # flagged, not failed
    assert any("cns_target" in fl for fl in f.flags)
    # negative control: no flag when the target is not in the CNS
    g = rf.assess_delivery({"name": "an-antibody"}, Route.SUBCUTANEOUS,
                           Modality.PROTEIN_ANTIBODY, exposure_profile=prof, cns_target=False)
    assert not any("cns_target" in fl for fl in g.flags)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
