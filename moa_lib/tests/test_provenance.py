# -*- coding: utf-8 -*-
"""Tests for the Step-0 gate (`moa_lib.provenance`).

Run from the repo root:
    C:\\Users\\Joseph\\.conda\\envs\\moa\\python.exe -m pytest moa_lib/tests/test_provenance.py -v

Every behaviour the gate is responsible for has BOTH a positive test and a negative
control, so a test that passes for the wrong reason is visible:

    HALT on composition mismatch        <-> the authentic variant must NOT halt
    user-provided variant proceeds      <-> the SAME list without that declaration HALTs
    identity verified for real drugs    <-> two different molecules HALT as a conflict,
                                            a hydrate-only record asks for the parent,
                                            a single source is insufficient
    topical does NOT halt               <-> topical to an unreachable tissue DOES stop
    EXPOSURE_MISMATCH on unreachability <-> as_is reaches -> no stop; dds_enabled -> no stop
    exposure never silently passes      <-> an unavailable resolver -> NEEDS_INPUT

Identity fixtures are REAL records, retrieved 2026-11-10:
    PubChem PUG-REST  /compound/name/<name>/property/InChIKey   (CID + InChIKey)
    ChEMBL REST       /data/molecule/<id>.json                  (standard_inchi_key +
                                                                 molecule_hierarchy)
No InChIKey in this file was written by hand.
"""
import pytest

from moa_lib import provenance as P

# ======================================================================================
# Fixtures — real identity records (see module docstring for retrieval paths)
# ======================================================================================
# Four APPROVED single molecules. The v11 gate HALTed every one of these because they
# are not herbal formulas in FORMULA_REF; a Step-0 agent had to override it by hand four
# times. They must now pass through the module path with no override.
APPROVED_SMALL_MOLECULES = {
    "atorvastatin": {
        "pubchem": {"cid": "60823", "inchikey": "XUKUURHRXDUEBC-KAYWLYCHSA-N"},
        "chembl": {"chembl_id": "CHEMBL1487", "parent_chembl_id": "CHEMBL1487",
                   "inchikey": "XUKUURHRXDUEBC-KAYWLYCHSA-N",
                   "molecule_type": "Small molecule"},
    },
    "ruxolitinib": {
        "pubchem": {"cid": "25126798", "inchikey": "HFNKQEVNSGCOJV-OAHLLOKOSA-N"},
        "chembl": {"chembl_id": "CHEMBL1789941", "parent_chembl_id": "CHEMBL1789941",
                   "inchikey": "HFNKQEVNSGCOJV-OAHLLOKOSA-N",
                   "molecule_type": "Small molecule"},
    },
    "tacrolimus": {
        # ChEMBL's TACROLIMUS record (CHEMBL3989887) is the MONOHYDRATE; its parent
        # CHEMBL269732 ("TACROLIMUS ANHYDROUS") is what agrees with PubChem.
        "pubchem": {"cid": "445643", "inchikey": "QJJXYPPXXYFBGM-LFZNUXCKSA-N",
                    "is_parent": True},
        "chembl": {"chembl_id": "CHEMBL269732", "parent_chembl_id": "CHEMBL269732",
                   "inchikey": "QJJXYPPXXYFBGM-LFZNUXCKSA-N",
                   "molecule_type": "Small molecule"},
    },
    "latanoprost": {
        "pubchem": {"cid": "5311221", "inchikey": "GGXICVAJURFBLW-CEYXHVGTSA-N"},
        "chembl": {"chembl_id": "CHEMBL1051", "parent_chembl_id": "CHEMBL1051",
                   "inchikey": "GGXICVAJURFBLW-CEYXHVGTSA-N",
                   "molecule_type": "Small molecule"},
    },
}

APPROVED_ROUTES = {"atorvastatin": ("oral", "hypercholesterolaemia", "liver"),
                   "ruxolitinib": ("topical", "atopic dermatitis", "skin_epidermis"),
                   "tacrolimus": ("topical", "atopic dermatitis", "skin_epidermis"),
                   "latanoprost": ("ophthalmic", "glaucoma", "eye_anterior")}

# 七白散 — the authentic 7-herb variant held in FORMULA_REF, and the WRONG 5-herb list
# that Session 9 actually analysed.
AUTHENTIC_7 = ["白蘞", "白朮", "白牽牛", "白芍藥", "白僵蠶", "白芷", "白附子"]
SESSION9_WRONG_5 = ["白朮 Atractylodes", "白芷 Angelica dahurica", "白及 Bletilla striata",
                    "白蘞 Ampelopsis japonica", "白茯苓 Poria cocos"]
LAB_PREPARATION = ["白朮", "白芷", "白及", "白茯苓", "甘草"]


def _reach(level, **kw):
    """A stand-in for one `moa_lib.exposure` reachability result (see EXPOSURE_INTERFACE)."""
    base = {"level": level, "compartments": kw.pop("compartments", ["skin_epidermis"]),
            "dds_bridgeable": kw.pop("dds_bridgeable", False),
            "dds_candidates": kw.pop("dds_candidates", []),
            "sources": kw.pop("sources", ["test fixture"]),
            "evidence_tier": kw.pop("evidence_tier", "E1")}
    base.update(kw)
    return base


REACH_OK = _reach("as_is")
REACH_NO = _reach("not_deliverable_to_target_tissue", compartments=["skin_epidermis"])


# ======================================================================================
# 1. Composition: the Session-9 wrong list must still HALT
# ======================================================================================
def test_session9_wrong_five_herb_list_halts():
    g = P.provenance_gate("Qibai San (七白散)", SESSION9_WRONG_5, "Atopic Dermatitis",
                          modality="herbal_formula", disease_tissue="skin_epidermis",
                          reachability=REACH_OK)
    assert g.action == P.HALT
    assert g.composition.verdict == "mismatch"
    assert g.halt_file == "HALT_provenance.md"
    joined = " ".join(g.composition.reasons)
    # the diff must name what is actually wrong, not just say "mismatch"
    assert "白牽牛" in joined or "pharbitis" in joined.lower()
    assert "白及" in joined or "白茯苓" in joined          # the non-authentic members
    assert "5 != 7" in joined


def test_session9_halt_report_lists_the_variant_diff():
    g = P.provenance_gate("七白散", SESSION9_WRONG_5, "Atopic Dermatitis",
                          modality="herbal_formula")
    body = P.halt_report(g)
    assert "mis-specified object of study" in body
    assert "qibai_7herb_taiping_yonglei" in body          # the sourced variant it was compared to


def test_another_wrong_list_also_halts():
    """Negative control for the matcher: a different wrong list must halt too."""
    g = P.provenance_gate("七白散", ["白朮", "白芷"], "Atopic Dermatitis",
                          modality="herbal_formula")
    assert g.action == P.HALT


def test_one_swapped_herb_halts():
    """Negative control: the matcher is not rubber-stamping any 7-herb list."""
    swapped = list(AUTHENTIC_7)
    swapped[2] = "甘草"                                    # 白牽牛 -> liquorice
    g = P.provenance_gate("七白散", swapped, "Atopic Dermatitis", modality="herbal_formula")
    assert g.action == P.HALT
    assert g.composition.verdict == "mismatch"


# ======================================================================================
# 2. Composition: the authentic variant passes AND names itself
# ======================================================================================
def test_authentic_variant_passes_and_names_the_variant():
    c = P.validate_composition("七白散", AUTHENTIC_7)
    assert c.verdict == "match"
    assert c.matched_variant == "qibai_7herb_taiping_yonglei"
    assert "太平聖惠方" in c.variant_source
    assert c.variant_source_kind == "classical"
    assert c.missing == [] and c.extra == []


def test_authentic_variant_does_not_halt():
    g = P.provenance_gate("七白散", AUTHENTIC_7, "Atopic Dermatitis",
                          modality="herbal_formula", disease_tissue="skin_epidermis",
                          reachability=REACH_OK)
    assert g.action != P.HALT
    assert g.composition.matched_variant == "qibai_7herb_taiping_yonglei"


def test_formula_ref_holds_a_list_of_variants():
    """Structural guarantee: variants are a list, so more can be added."""
    rec = P.FORMULA_REF["qibai san"]
    assert isinstance(rec["variants"], list) and len(rec["variants"]) >= 1
    for v in rec["variants"]:
        assert v["source"] and v["source_kind"] and v["variant_id"]
        assert v["herb_count"] == len(v["herbs"])


# ======================================================================================
# 3. A lab's own preparation proceeds, recorded as user-provided
# ======================================================================================
def test_lab_variant_proceeds_as_user_provided():
    g = P.provenance_gate("七白散", LAB_PREPARATION, "Atopic Dermatitis",
                          modality="herbal_formula",
                          composition_source={"kind": "user_provided",
                                              "source": "Lab X internal preparation SOP, 2026"},
                          disease_tissue="skin_epidermis", reachability=REACH_OK)
    assert g.action != P.HALT
    assert g.composition.verdict == "user_provided_variant"
    assert g.composition.is_user_provided
    assert "Lab X" in g.composition.variant_source
    assert "user_provided_composition" in g.labels
    # the run must carry the fact forward so the report can state it
    assert any("lab's" in r for r in g.reasons)
    # and the difference from the classical variant is still recorded
    assert g.composition.candidate_variants


def test_same_list_without_the_user_provided_declaration_halts():
    """Negative control: `user_provided` is a declaration, not a blanket bypass."""
    g = P.provenance_gate("七白散", LAB_PREPARATION, "Atopic Dermatitis",
                          modality="herbal_formula")
    assert g.action == P.HALT
    assert g.composition.verdict == "mismatch"


def test_unsourceable_composition_halts():
    g = P.provenance_gate("七白散", LAB_PREPARATION, "Atopic Dermatitis",
                          modality="herbal_formula",
                          composition_source={"kind": "unsourceable"})
    assert g.action == P.HALT
    assert g.composition.verdict == "unsourceable"


def test_unknown_formula_returns_needs_input_with_both_caller_options():
    """An unknown formula is a question, not a dead end: the module hands the caller a
    question AND a halt-report body, and does not choose between them."""
    g = P.provenance_gate("某某散 (unlisted formula)", ["甲", "乙", "丙"], "Psoriasis",
                          modality="herbal_formula")
    assert g.action == P.NEEDS_INPUT
    assert g.composition.verdict == "unknown"
    assert g.required_inputs and g.question["needs"] == g.required_inputs
    assert set(g.caller_options) == {"ask_user", "write_halt_file"}
    assert P.halt_filename(g) == "HALT_provenance.md"
    assert "What is needed" in P.halt_report(g)


def test_unknown_formula_with_a_source_proceeds():
    g = P.provenance_gate("某某散 (unlisted formula)", ["甲", "乙", "丙"], "Psoriasis",
                          modality="herbal_formula",
                          composition_source={"kind": "classical",
                                              "source": "《某某方》 juan 3"})
    assert g.action != P.HALT and g.action != P.NEEDS_INPUT
    assert g.composition.verdict == "sourced_external"


# ======================================================================================
# 4. Identity per modality — four approved single molecules, no hand override
# ======================================================================================
@pytest.mark.parametrize("drug", sorted(APPROVED_SMALL_MOLECULES))
def test_approved_small_molecule_identity_verifies(drug):
    ev = APPROVED_SMALL_MOLECULES[drug]
    chk = P.verify_identity("small_molecule", drug, ev)
    assert chk.verdict == "verified", chk
    assert chk.evidence_tier == "E0"
    assert chk.missing == [] and chk.conflicts == []
    assert "InChIKey parent skeleton" in chk.matched_on[0]


@pytest.mark.parametrize("drug", sorted(APPROVED_SMALL_MOLECULES))
def test_approved_small_molecule_passes_the_gate_without_override(drug):
    route, disease, tissue = APPROVED_ROUTES[drug]
    g = P.provenance_gate(drug, None, disease, modality="small_molecule", route=route,
                          route_source="approved label",
                          identity_evidence=APPROVED_SMALL_MOLECULES[drug],
                          indication_evidence={"approved": [
                              {"indication": disease, "source": "approved label"}]},
                          disease_tissue=tissue, reachability=REACH_OK)
    assert g.action == P.PASS, g.reasons
    assert g.identity.verdict == "verified"
    assert g.composition.verdict == "not_applicable"
    assert g.indication_status == "approved"
    # approved in the indication -> the circularity control must be switched on
    assert g.circularity.triggered and "circularity_control_required" in g.labels


def test_two_different_molecules_are_an_identity_conflict_and_halt():
    """Negative control: the InChIKey check must actually compare skeletons."""
    ev = {"pubchem": APPROVED_SMALL_MOLECULES["atorvastatin"]["pubchem"],
          "chembl": APPROVED_SMALL_MOLECULES["ruxolitinib"]["chembl"]}
    chk = P.verify_identity("small_molecule", "atorvastatin", ev)
    assert chk.verdict == "conflict" and chk.halts
    g = P.provenance_gate("atorvastatin", None, "hypercholesterolaemia",
                          modality="small_molecule", route="oral", identity_evidence=ev)
    assert g.action == P.HALT
    assert "identity not verified" in " ".join(g.reasons)


def test_hydrate_record_asks_for_the_parent_instead_of_halting():
    """The real ChEMBL TACROLIMUS record is the monohydrate: a different form, not a
    different molecule. The gate must ask for the parent, not reject the drug."""
    ev = {"pubchem": {"cid": "445643", "inchikey": "QJJXYPPXXYFBGM-LFZNUXCKSA-N"},
          "chembl": {"chembl_id": "CHEMBL3989887", "parent_chembl_id": "CHEMBL269732",
                     "inchikey": "NWJQLQGQZSIBAF-MLAUYUEBSA-N"}}
    chk = P.verify_identity("small_molecule", "tacrolimus", ev)
    assert chk.verdict == "insufficient"
    assert any("CHEMBL269732" in m for m in chk.missing)
    g = P.provenance_gate("tacrolimus", None, "atopic dermatitis", modality="small_molecule",
                          route="topical", identity_evidence=ev)
    assert g.action == P.NEEDS_INPUT


def test_single_source_is_insufficient():
    ev = {"pubchem": APPROVED_SMALL_MOLECULES["latanoprost"]["pubchem"]}
    chk = P.verify_identity("small_molecule", "latanoprost", ev)
    assert chk.verdict == "insufficient"
    assert any("second independent" in m for m in chk.missing)


def test_recorded_negative_lookups_are_unverifiable_and_halt():
    """Looked and found nothing is NOT the same as not having looked: it HALTs."""
    ev = {"pubchem": {"status": "not_found"}, "chembl": {"status": "not_found"}}
    chk = P.verify_identity("small_molecule", "unobtainium-7", ev)
    assert chk.verdict == "unverifiable" and chk.halts
    g = P.provenance_gate("unobtainium-7", None, "psoriasis", modality="small_molecule",
                          route="oral", identity_evidence=ev)
    assert g.action == P.HALT


def test_no_identity_evidence_is_needs_input_not_halt():
    chk = P.verify_identity("small_molecule", "atorvastatin", None)
    assert chk.verdict == "not_supplied" and chk.needs_input
    assert any("pubchem" in m.lower() for m in chk.missing)


def test_stereo_difference_verifies_with_a_note():
    ev = {"pubchem": {"cid": "1", "inchikey": "XUKUURHRXDUEBC-KAYWLYCHSA-N"},
          "chembl": {"chembl_id": "CHEMBL1487", "parent_chembl_id": "CHEMBL1487",
                     "inchikey": "XUKUURHRXDUEBC-UHFFFAOYSA-N"}}
    chk = P.verify_identity("small_molecule", "atorvastatin", ev)
    assert chk.verdict == "verified"
    assert any("full InChIKeys differ" in n for n in chk.notes)


def test_antibody_identity_requires_inn_chembl_target_and_label():
    full = {"inn": "dupilumab",
            "chembl": {"chembl_id": "CHEMBL3833319", "molecule_type": "Antibody"},
            "uniprot_target": ["P24394"],
            "label": {"source": "FDA label, DailyMed set id"}}
    assert P.verify_identity("antibody", "dupilumab", full).verdict == "verified"
    for drop in ("inn", "chembl", "uniprot_target", "label"):
        partial = {k: v for k, v in full.items() if k != drop}
        chk = P.verify_identity("antibody", "dupilumab", partial)
        assert chk.verdict == "insufficient", drop
        assert chk.missing, drop


def test_oligonucleotide_identity_needs_sequence_backbone_and_resolved_transcript():
    full = {"sequence": ["GCAAGAAAGGGCUUCAUCCUU"],
            "backbone": "siRNA duplex, 2'-OMe/2'-F, phosphorothioate, triantennary GalNAc",
            "target_transcript": {"gene": "PCSK9", "refseq": "NM_174936",
                                  "source": "sequence alignment (BLASTn), PMID:00000000"}}
    assert P.verify_identity("oligonucleotide", "inclisiran", full).verdict == "verified"
    # a transcript asserted without the resolution source is not resolved FROM the sequence
    nosrc = dict(full, target_transcript={"gene": "PCSK9", "refseq": "NM_174936"})
    chk = P.verify_identity("oligonucleotide", "inclisiran", nosrc)
    assert chk.verdict == "insufficient"
    assert any("source" in m for m in chk.missing)
    # a non-nucleotide sequence is a conflict, not a pass
    bad = dict(full, sequence=["GCAAGXZQUUU"])
    assert P.verify_identity("oligonucleotide", "inclisiran", bad).verdict == "conflict"


def test_cell_therapy_identity_needs_type_source_and_construct():
    full = {"cell_type": "autologous CD3+ T cell",
            "source": "patient leukapheresis (autologous)",
            "construct": {"car_target": "CD19", "vector": "lentiviral",
                          "source": "approved label"}}
    assert P.verify_identity("cell_therapy", "tisagenlecleucel", full).verdict == "verified"
    chk = P.verify_identity("cell_therapy", "tisagenlecleucel",
                            {k: v for k, v in full.items() if k != "construct"})
    assert chk.verdict == "insufficient"


def test_ev_identity_against_the_chosen_misev_items():
    full = {"source_cell_type": "human adipose-derived stem cell (ADSC)",
            "isolation_method": "differential ultracentrifugation + size-exclusion chromatography",
            "positive_markers": ["CD9", "CD81", "TSG101"],     # transmembrane + cytosolic
            "negative_markers": ["calnexin"],
            "particle_characterisation": ["TEM", "NTA"]}
    chk = P.verify_identity("exosome", "ADSC-EV", full)
    assert chk.verdict == "verified"
    assert chk.evidence_tier == "E1"                           # characterised, never E0
    assert any("hypothesis-level" in n for n in chk.notes)
    # three markers but all transmembrane -> the topology demonstration is missing
    tm_only = dict(full, positive_markers=["CD9", "CD63", "CD81"])
    chk2 = P.verify_identity("exosome", "ADSC-EV", tm_only)
    assert chk2.verdict == "insufficient"
    assert any("cytosolic=NO" in m for m in chk2.missing)
    # each chosen MISEV item must be individually required
    for drop in ("source_cell_type", "isolation_method", "negative_markers",
                 "particle_characterisation"):
        partial = {k: v for k, v in full.items() if k != drop}
        chk3 = P.verify_identity("extracellular_vesicle", "ADSC-EV", partial)
        assert chk3.verdict == "insufficient", drop
        assert any(drop in m for m in chk3.missing), drop


def test_every_misev_item_has_a_documented_reason():
    assert set(P.MISEV_MIN_ITEMS) == {"source_cell_type", "isolation_method", "positive_markers",
                                      "negative_markers", "particle_characterisation"}
    for item, why in P.MISEV_MIN_ITEMS.items():
        assert len(why) > 40, item


# ======================================================================================
# 5. Topical no longer HALTs — it sets the exposure profile
# ======================================================================================
def test_topical_formula_does_not_halt():
    g = P.provenance_gate("七白散", AUTHENTIC_7, "Atopic Dermatitis",
                          modality="herbal_formula", disease_tissue="skin_epidermis",
                          reachability=REACH_OK)
    assert g.action == P.REFRAME                     # a repurposing hypothesis, not a stop
    assert g.action != P.HALT
    assert g.route == "topical" and g.exposure_route == "topical_skin"
    assert g.route_evidence_tier == "E1"             # the classical source names the route
    assert "repurposing_hypothesis" in g.labels
    assert not any("category error" in r for r in g.reasons)


def test_topical_small_molecule_does_not_halt():
    g = P.provenance_gate("ruxolitinib", None, "atopic dermatitis", modality="small_molecule",
                          route="topical", formulation="cream", route_source="approved label",
                          identity_evidence=APPROVED_SMALL_MOLECULES["ruxolitinib"],
                          indication_evidence={"approved": [{"indication": "atopic dermatitis",
                                                             "source": "approved label"}]},
                          disease_tissue="skin_epidermis", reachability=REACH_OK)
    assert g.action == P.PASS
    assert g.formulation == "cream"


def test_topical_is_still_stopped_when_the_tissue_is_out_of_reach():
    """Negative control for "topical never halts": the stop is about reach, not route."""
    g = P.provenance_gate("ruxolitinib", None, "myelofibrosis", modality="small_molecule",
                          route="topical", formulation="cream",
                          identity_evidence=APPROVED_SMALL_MOLECULES["ruxolitinib"],
                          disease_tissue="bone_marrow", reachability=REACH_NO)
    assert g.action == P.EXPOSURE_MISMATCH


def test_route_classification_is_not_a_stop_decision():
    r = P.classify_route("七白散")
    route, source = r                                 # still unpacks as the v11 2-tuple
    assert route == "topical" and "太平聖惠方" in source
    assert r.exposure_route == "topical_skin" and r.evidence_tier == "E1"
    # a caller-supplied route wins (same molecule, different product)
    r2 = P.classify_route("ruxolitinib", route="oral", route_source="approved label")
    assert r2.route == "oral" and r2.exposure_route == "oral" and r2.level == "caller_supplied"


# ======================================================================================
# 6. EXPOSURE_MISMATCH
# ======================================================================================
def test_exposure_mismatch_returns_its_own_verdict_and_file():
    g = P.provenance_gate("ruxolitinib", None, "myelofibrosis", modality="small_molecule",
                          route="topical", formulation="cream", route_source="approved label",
                          identity_evidence=APPROVED_SMALL_MOLECULES["ruxolitinib"],
                          indication_evidence={"approved": [
                              {"indication": "myelofibrosis (ORAL product)",
                               "source": "approved label"}]},
                          disease_tissue="bone_marrow",
                          reachability=_reach("not_deliverable_to_target_tissue",
                                              compartments=["skin_epidermis", "skin_dermis"],
                                              sources=["label: topical, minimal systemic exposure"]))
    assert g.action == P.EXPOSURE_MISMATCH
    assert g.halt_file == "HALT_exposure_mismatch.md"
    assert g.exposure.mismatch and g.exposure.reachable is False
    body = P.halt_report(g)
    for token in ("bone_marrow", "skin_epidermis", "topical"):
        assert token in body


def test_exposure_mismatch_carries_dds_bridgeability_for_the_development_path():
    g = P.provenance_gate("militarine-like constituent", None, "psoriasis",
                          modality="small_molecule", route="topical",
                          identity_evidence=APPROVED_SMALL_MOLECULES["atorvastatin"],
                          disease_tissue="skin_dermis",
                          reachability=_reach("not_deliverable_to_target_tissue",
                                              dds_bridgeable=True,
                                              dds_candidates=["nanoemulsion", "microneedle array"],
                                              compartments=["stratum_corneum"]))
    assert g.action == P.EXPOSURE_MISMATCH
    assert g.exposure.dds_bridgeable
    assert "development_path" in g.labels
    body = P.halt_report(g)
    assert "microneedle array" in body
    assert "development path" in body


def test_reachable_tissue_does_not_stop_the_run():
    """Negative control: EXPOSURE_MISMATCH must depend on the reachability result."""
    g = P.provenance_gate("ruxolitinib", None, "atopic dermatitis", modality="small_molecule",
                          route="topical", identity_evidence=APPROVED_SMALL_MOLECULES["ruxolitinib"],
                          indication_evidence={"approved": [{"indication": "atopic dermatitis",
                                                             "source": "label"}]},
                          disease_tissue="skin_epidermis", reachability=REACH_OK)
    assert g.action == P.PASS
    assert g.exposure.mismatch is False


def test_dds_enabled_proceeds_but_is_labelled_delivery_dependent():
    g = P.provenance_gate("semaglutide", None, "obesity", modality="peptide", route="oral",
                          identity_evidence={"inn": "semaglutide",
                                             "chembl": {"chembl_id": "CHEMBL3137343",
                                                        "molecule_type": "Protein"},
                                             "uniprot_target": ["P43220"],
                                             "label": {"source": "approved label"}},
                          indication_evidence={"approved": [{"indication": "obesity",
                                                             "source": "approved label"}]},
                          disease_tissue="hypothalamus",
                          reachability=_reach("dds_enabled",
                                              dds_candidates=["SNAC permeation enhancer"],
                                              compartments=["plasma"]))
    assert g.action == P.PASS
    assert "delivery_dependent" in g.labels
    assert g.exposure.level == "dds_enabled"


def test_exposure_is_never_a_silent_pass_when_it_cannot_be_resolved(monkeypatch):
    monkeypatch.setattr(P, "_load_exposure_resolver",
                        lambda: (None, "stub: moa_lib.exposure unavailable"))
    g = P.provenance_gate("atorvastatin", None, "hypercholesterolaemia",
                          modality="small_molecule", route="oral",
                          identity_evidence=APPROVED_SMALL_MOLECULES["atorvastatin"],
                          indication_evidence={"approved": [{"indication": "x", "source": "label"}]},
                          disease_tissue="liver")
    assert g.action == P.NEEDS_INPUT
    assert any("exposure reachability" in r for r in g.required_inputs)


def test_exposure_resolver_errors_are_reported_not_swallowed():
    def boom(**kwargs):
        raise RuntimeError("exposure model unavailable")

    chk = P.resolve_reachability("liver", modality="small_molecule", route="oral",
                                 exposure_resolver=boom)
    assert chk.level == "not_assessable"
    assert any("RuntimeError" in r for r in chk.reasons)


def test_exposure_resolver_is_called_with_the_normalised_route():
    seen = {}

    def resolver(*, tissue, modality, route, formulation=None, profile=None):
        seen.update(tissue=tissue, modality=modality, route=route, formulation=formulation)
        return _reach("as_is")

    chk = P.resolve_reachability("skin_epidermis", modality="herbal", route="topical",
                                 formulation="mask", exposure_resolver=resolver)
    assert seen == {"tissue": "skin_epidermis", "modality": "herbal_formula",
                    "route": "topical_skin", "formulation": "mask"}
    assert chk.level == "as_is" and chk.reachable is True


def test_resolver_with_a_narrow_signature_is_still_callable():
    """The exposure module may not accept every kwarg; only accepted ones are passed."""
    def narrow(tissue, route):
        return {"reachable": True, "compartments": ["liver"], "sources": ["label"]}

    chk = P.resolve_reachability("liver", modality="small_molecule", route="oral",
                                 exposure_resolver=narrow)
    assert chk.reachable is True and chk.level == "as_is"


def test_missing_tissue_of_pathology_is_reported_not_assumed():
    chk = P.resolve_reachability(None, modality="small_molecule", route="oral")
    assert chk.assessed is False and chk.level == "not_assessed"
    assert any("tissue of pathology not supplied" in r for r in chk.reasons)


def test_exposure_interface_contract_is_documented():
    for token in ("reaches_target_tissue", "dds_bridgeable", "not_deliverable_to_target_tissue",
                  "evidence_tier", "not_assessable"):
        assert token in P.EXPOSURE_INTERFACE


def test_exposure_mismatch_tuple_return_is_accepted():
    """`exposure.exposure_mismatch()` returns (is_mismatch, Reachability)."""
    chk = P.resolve_reachability("bone_marrow", modality="small_molecule", route="topical",
                                 reachability=(True, _reach("not_deliverable_to_target_tissue")))
    assert chk.mismatch is True


def test_exposure_module_vocabulary_is_understood():
    """The real module reports `verdict`/`route_compartments`/`rationale`/`provisional`."""
    raw = {"verdict": "reachable_systemic", "reachable": True, "tissue": "liver",
           "target_compartment": "liver", "route_compartments": ["plasma", "gut_lumen"],
           "via": "systemic", "provisional": True, "rationale": ["full systemic exposure"],
           "sources": [{"citation": "label", "kind": "label", "detail": "oral tablet"}]}
    chk = P.resolve_reachability("liver", modality="small_molecule", route="oral",
                                 reachability=raw)
    assert chk.level == "reachable_systemic" and chk.reachable is True
    assert chk.mismatch is False and chk.assessed is True
    assert chk.compartments == ["plasma", "gut_lumen"]
    assert chk.target_compartment == "liver" and chk.via == "systemic"
    assert chk.provisional is True
    assert chk.sources == ["[label] label — oral tablet"]
    assert "full systemic exposure" in chk.reasons


def test_reachable_verdict_without_an_explicit_flag_is_derived():
    """The exposure model may report only a verdict; both of its reachable verdicts count."""
    for verdict in ("reachable_direct", "reachable_systemic"):
        chk = P.resolve_reachability("liver", modality="small_molecule", route="oral",
                                     reachability={"verdict": verdict,
                                                   "route_compartments": ["plasma"]})
        assert chk.reachable is True, verdict
        assert chk.assessed is True and chk.mismatch is False, verdict
    # and an unreachable verdict with no explicit flag still stops the run
    chk = P.resolve_reachability("bone_marrow", modality="small_molecule", route="topical",
                                 reachability={"verdict": "not_deliverable_to_target_tissue"})
    assert chk.reachable is False and chk.mismatch is True


def test_not_assessable_is_never_a_pass_even_if_reachable_is_set():
    chk = P.resolve_reachability("unmappable_tissue", modality="small_molecule", route="oral",
                                 reachability={"verdict": "not_assessable", "reachable": True})
    assert chk.assessed is False and chk.reachable is None and chk.mismatch is False
    g = P.provenance_gate("atorvastatin", None, "x", modality="small_molecule", route="oral",
                          identity_evidence=APPROVED_SMALL_MOLECULES["atorvastatin"],
                          disease_tissue="unmappable_tissue",
                          reachability={"verdict": "not_assessable", "reachable": True})
    assert g.action == P.NEEDS_INPUT


def test_caller_supplied_dds_candidates_are_merged_in():
    """moa_lib.exposure does not model delivery systems; route_feasibility supplies them."""
    g = P.provenance_gate("militarine", None, "psoriasis", modality="small_molecule",
                          route="topical", identity_evidence=APPROVED_SMALL_MOLECULES["atorvastatin"],
                          disease_tissue="skin_dermis", reachability=REACH_NO,
                          dds_candidates=["nanoemulsion"])
    assert g.action == P.EXPOSURE_MISMATCH
    assert g.exposure.dds_bridgeable and g.exposure.dds_candidates == ["nanoemulsion"]
    assert "development_path" in g.labels


def test_provisional_profile_is_labelled():
    g = P.provenance_gate("atorvastatin", None, "x", modality="small_molecule", route="oral",
                          identity_evidence=APPROVED_SMALL_MOLECULES["atorvastatin"],
                          indication_evidence={"approved": [{"source": "label"}]},
                          disease_tissue="liver",
                          reachability=_reach("reachable_systemic", provisional=True,
                                              evidence_tier="E4"))
    assert "provisional_exposure_profile" in g.labels


# --- integration with the real moa_lib.exposure (skipped only if it is absent) ---------
_exposure = pytest.importorskip("moa_lib.exposure",
                                reason="moa_lib.exposure not present in this tree")


def test_real_exposure_module_satisfies_the_documented_contract():
    fn, info = P._load_exposure_resolver()
    assert fn is not None, info
    assert info.startswith("moa_lib.exposure.")


def test_real_exposure_module_stops_a_topical_run_aimed_at_marrow():
    """End-to-end through the real exposure model: no stub reachability."""
    g = P.provenance_gate("ruxolitinib", None, "myelofibrosis", modality="small_molecule",
                          route="topical_skin", formulation="cream",
                          route_source="approved label",
                          identity_evidence=APPROVED_SMALL_MOLECULES["ruxolitinib"],
                          disease_tissue="bone marrow")
    assert g.action == P.EXPOSURE_MISMATCH, g.reasons
    assert g.exposure.resolver.startswith("moa_lib.exposure.")
    assert g.exposure.compartments                     # the model reported the route's reach


def test_real_exposure_module_lets_the_matching_tissue_through():
    g = P.provenance_gate("ruxolitinib", None, "atopic dermatitis", modality="small_molecule",
                          route="topical_skin", formulation="cream",
                          route_source="approved label",
                          identity_evidence=APPROVED_SMALL_MOLECULES["ruxolitinib"],
                          indication_evidence={"approved": [{"indication": "atopic dermatitis",
                                                             "source": "approved label"}]},
                          disease_tissue="lesional skin")
    assert g.action in (P.PASS, P.REFRAME), g.reasons
    assert g.action != P.EXPOSURE_MISMATCH
    assert g.exposure.reachable is True


def test_real_exposure_module_uses_the_formula_route_source_for_a_herbal_run():
    g = P.provenance_gate("七白散", AUTHENTIC_7, "Atopic Dermatitis", modality="herbal_formula",
                          formulation="mask", disease_tissue="lesional skin")
    assert g.action == P.REFRAME                       # repurposing hypothesis, never a stop
    assert g.exposure.assessed and g.exposure.reachable is True


# ======================================================================================
# 7. Indication plausibility — four values
# ======================================================================================
def test_four_indication_values():
    assert P.indication_plausibility(
        "x", "d", evidence={"approved": [{"source": "label"}]}).status == "approved"
    assert P.indication_plausibility(
        "x", "d", evidence={"trialled": [{"nct": "NCT00000000"}]}).status == "trialled"
    assert P.indication_plausibility(
        "x", "d", evidence={"literature": [{"pmid": "1", "grounded": True,
                                            "claim": "c"}]}).status == "literature_supported"
    assert P.indication_plausibility("x", "d").status == "none"


def test_ungrounded_literature_is_not_e1():
    r = P.indication_plausibility("x", "d", evidence={"literature": [{"pmid": "1",
                                                                      "grounded": False}]})
    assert r.status == "none"
    assert r.ungrounded and "citation grounding" in r.why


def test_user_claim_is_recorded_but_never_e1():
    r = P.indication_plausibility("七白散", "Atopic Dermatitis", evidence={
        "user_claim": [{"statement": "our lab found it works", "published": False}]})
    assert r.status == "none"
    assert r.evidence_tier != "E1"
    assert r.user_claims and "user-provided claim" in r.why
    g = P.provenance_gate("七白散", AUTHENTIC_7, "Atopic Dermatitis", modality="herbal_formula",
                          indication_evidence={"user_claim": [
                              {"statement": "our lab found it works", "published": False}]})
    assert g.action == P.REFRAME
    assert "user_provided_efficacy_claim" in g.labels


def test_published_and_grounded_user_claim_becomes_e1():
    r = P.indication_plausibility("七白散", "Atopic Dermatitis", evidence={
        "user_claim": [{"statement": "our lab found it works", "published": True,
                        "pmid": "39999999", "grounded": True}]})
    assert r.status == "literature_supported" and r.evidence_tier == "E1"


def test_traditional_use_is_not_demonstrated_efficacy():
    r = P.indication_plausibility("七白散", "skin whitening")
    assert r.status == "none" and r.traditional_use is True
    assert "not demonstrated efficacy" in r.why
    g = P.provenance_gate("七白散", AUTHENTIC_7, "skin whitening", modality="herbal_formula")
    assert g.action == P.REFRAME and "traditional_use_only" in g.labels


def test_indication_result_still_unpacks_as_the_v11_tuple():
    status, why = P.indication_plausibility("七白散", "Atopic Dermatitis")
    assert status == "novel/implausible" and isinstance(why, str)
    status2, _ = P.indication_plausibility("七白散", "skin whitening")
    assert status2 == "established"          # v11 called a traditional match "established"


# ======================================================================================
# 8. Circularity control
# ======================================================================================
TRIAL_PAPER = {"pmid": "1", "title": "Semaglutide and weight loss in obesity (STEP 1)",
               "abstract": "A randomised trial of semaglutide 2.4 mg.",
               "publication_types": ["Randomized Controlled Trial", "Journal Article"]}
REVIEW_PAPER = {"pmid": "2", "title": "Semaglutide: a review of GLP-1 receptor agonists",
                "abstract": "We review semaglutide trials.",
                "publication_types": ["Review"]}
TARGET_PAPER = {"pmid": "3", "title": "GLP1R signalling in hypothalamic neurons",
                "abstract": "Receptor biology in mice.",
                "publication_types": ["Journal Article"]}
NCT_PAPER = {"pmid": "4", "title": "Semaglutide in adolescents",
             "abstract": "Protocol registered as NCT04102189.",
             "publication_types": ["Journal Article"]}
NO_TYPES = {"pmid": "5", "title": "Semaglutide something", "abstract": "", "publication_types": []}


def test_circularity_triggers_on_approved_and_trialled_only():
    assert P.circularity_spec("semaglutide", "obesity", "approved").triggered
    assert P.circularity_spec("semaglutide", "obesity", "trialled").triggered
    assert not P.circularity_spec("x", "d", "literature_supported").triggered
    assert not P.circularity_spec("x", "d", "none").triggered


def test_circularity_strips_both_legs_reported_separately():
    spec = P.circularity_spec("semaglutide", "obesity", "approved",
                              publications=[TRIAL_PAPER, REVIEW_PAPER, TARGET_PAPER,
                                            NCT_PAPER, NO_TYPES])
    assert len(spec.legs) == 2
    leg1, leg2 = spec.legs
    assert leg1["strip"]["datatypeId"] == ["known_drug"]
    assert leg1["report_as"] != leg2["report_as"]            # reported separately
    stripped = set(leg2["strip"]["pmids"])
    assert stripped == {"1", "2", "4"}                       # trial, review, NCT-registering
    assert "3" not in stripped                               # target biology is NOT stripped
    assert [u["pmid"] for u in spec.unclassifiable_pmids] == ["5"]
    assert spec.reporting["primary_unchanged"] is True
    assert any("own trial evidence" in r for r in spec.reporting["rules"])


def test_own_compound_literature_definition():
    assert P.is_own_compound_literature(TRIAL_PAPER, "semaglutide")[0] is True
    assert P.is_own_compound_literature(REVIEW_PAPER, "semaglutide")[0] is True
    assert P.is_own_compound_literature(NCT_PAPER, "semaglutide")[0] is True
    # negative controls
    ok, why = P.is_own_compound_literature(TARGET_PAPER, "semaglutide")
    assert ok is False and any("not about the compound" in w for w in why)
    ok2, why2 = P.is_own_compound_literature(
        dict(TARGET_PAPER, title="Semaglutide and GLP1R signalling"), "semaglutide")
    assert ok2 is False and any("neither trial nor review" in w for w in why2)
    ok3, why3 = P.is_own_compound_literature(NO_TYPES, "semaglutide")
    assert ok3 is False and any("unclassifiable" in w for w in why3)
    # an alias (brand name) also identifies the compound's own literature
    assert P.is_own_compound_literature(
        {"pmid": "9", "title": "Wegovy trial", "abstract": "",
         "publication_types": ["Clinical Trial, Phase III"]},
        "semaglutide", aliases=["Wegovy"])[0] is True
    # MeSH substance match, with no name in the title
    assert P.is_own_compound_literature(
        {"pmid": "10", "title": "Weight loss in adults", "abstract": "",
         "mesh_substances": ["Semaglutide"], "publication_types": ["Review"]},
        "semaglutide")[0] is True


def test_circularity_publication_types_are_documented_and_exclude_primary_research():
    assert "randomized controlled trial" in P.CIRCULARITY_PUBTYPES
    assert "review" in P.CIRCULARITY_PUBTYPES
    assert "journal article" not in P.CIRCULARITY_PUBTYPES


# ======================================================================================
# 9. v11 compatibility + serialisation
# ======================================================================================
def test_v11_positional_signature_and_action_strings():
    g = P.provenance_gate("Qibai San (七白散)", SESSION9_WRONG_5, "Atopic Dermatitis")
    assert isinstance(g.action, str) and g.action == "HALT"
    assert g.route == "topical" and isinstance(g.route_source, str)
    assert g.indication in ("established", "novel/implausible", "unknown")
    assert isinstance(g.composition, P.CompositionCheck)
    route, src = P.classify_route("七白散")               # 2-tuple unpack
    assert (route, isinstance(src, str)) == ("topical", True)


def test_gate_verdict_is_json_serialisable():
    import json
    g = P.provenance_gate("七白散", AUTHENTIC_7, "Atopic Dermatitis", modality="herbal_formula",
                          disease_tissue="skin_epidermis", reachability=REACH_OK)
    blob = json.dumps(g.as_dict(), ensure_ascii=False)
    assert "qibai_7herb_taiping_yonglei" in blob
    parsed = json.loads(blob)
    assert parsed["action"] == g.action
    # step0_data.json is consumed by Steps 1 and 5 — the exposure block must be complete
    assert set(parsed["exposure"]) == {"assessed", "tissue", "level", "reachable",
                                       "compartments", "target_compartment", "via",
                                       "provisional", "dds_bridgeable", "dds_candidates",
                                       "sources", "evidence_tier"}


def test_verdict_precedence_is_total_and_ordered():
    assert P.VERDICT_PRECEDENCE == (P.HALT, P.EXPOSURE_MISMATCH, P.NEEDS_INPUT,
                                    P.REFRAME, P.PASS)
    # a composition HALT wins over an exposure mismatch: the wrong object of study first
    g = P.provenance_gate("七白散", SESSION9_WRONG_5, "myelofibrosis",
                          modality="herbal_formula", disease_tissue="bone_marrow",
                          reachability=REACH_NO)
    assert g.action == P.HALT


def test_references_for_the_encoded_rules_exist():
    for key in ("MISEV2018", "MISEV2023"):
        assert P.REFERENCES[key]["doi"] and P.REFERENCES[key]["used_for"]
