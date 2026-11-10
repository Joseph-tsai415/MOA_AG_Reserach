"""Step-0 gate (v12) — is the OBJECT OF STUDY correctly specified?

This gate runs before any data fetch. It answers four questions and nothing else:

  1. **Identity** — is the thing we are about to analyse the thing the user means?
     Modality-aware (CLAUDE.md §3.4; kernel design §8.1 R2): InChIKey *parent* match
     for a small molecule, INN + biotherapeutic record + target + label for an
     antibody, sequence + backbone + target transcript for an oligonucleotide,
     cell type + source + construct for a cell therapy, MISEV minimum-information
     items for an extracellular vesicle, sourced composition for a herbal formula.
  2. **Composition** (herbal formulas) — does the provided herb list match a
     *sourced* variant of the formula? Several variants may be sourced; a lab's own
     preparation is recorded as a user-provided variant, with the lab as its source.
  3. **Exposure** — can the route reach the tissue of pathology? (kernel design §8.2 B3)
  4. **Indication plausibility** — approved / trialled / literature-supported (E1,
     grounded) / none, the last producing a REFRAME (repurposing-hypothesis) label.

It also emits the **circularity control specification** that Step 3 consumes when the
compound is approved or trialled in the indication (kernel design §8.2 B2).

What this module HALTs on — and only this — is a **mis-specified object of study**:

    HALT                 composition matches no sourced variant; composition cannot
                         be sourced; identity cannot be verified.
    EXPOSURE_MISMATCH    the route cannot reach the tissue of pathology. Carries
                         `dds_bridgeable` so the caller can route to the development
                         path instead of claiming systemic efficacy.
    NEEDS_INPUT          something required has not been supplied or fetched yet
                         (unknown formula, identity evidence missing, exposure not
                         resolvable). The module reports *what is needed* and hands the
                         caller both a question and a ready HALT-report body; it does
                         NOT decide between asking the user (interactive) and writing
                         `HALT_provenance.md` (service mode).
    REFRAME              the object of study is fine, but the indication is not
                         approved/trialled/E1-supported — label it a repurposing
                         hypothesis.
    PASS                 proceed.

**Topical no longer HALTs.** Session 9's real error was analysing a *wrong 5-herb
composition* of 七白散 as a *systemic* drug; the fix is to model skin exposure, not to
refuse to look. Route now feeds the exposure model (`classify_route`), and the only
exposure-driven stop is a genuine route-vs-tissue mismatch.

Public API (v11 names kept working; see "Compatibility" below)
--------------------------------------------------------------
    validate_composition(name, provided_herbs, *, composition_source=None) -> CompositionCheck
    classify_route(name, *, route=None, route_source=None, formulation=None) -> RouteInfo
    indication_plausibility(name, disease, *, evidence=None) -> IndicationResult
    verify_identity(modality, name, evidence=None, *, provided_herbs=None,
                    composition_source=None) -> IdentityCheck
    resolve_reachability(tissue, *, modality, route, formulation=None, profile=None,
                         reachability=None, exposure_resolver=None) -> ExposureCheck
    circularity_spec(compound, disease, indication_status, *, publications=None,
                     compound_aliases=None) -> CircularitySpec
    is_own_compound_literature(record, compound, aliases=()) -> (bool, reasons)
    provenance_gate(name, provided_herbs=None, disease=None, *, ...) -> GateVerdict
    halt_filename(verdict) -> str | None
    halt_report(verdict) -> str      # markdown body for the HALT file

Compatibility with v11 callers
------------------------------
`classify_route` and `indication_plausibility` still unpack as 2-tuples
(`route, source = classify_route(...)`), and `GateVerdict.action` is still a plain
string compared against "HALT"/"REFRAME"/"PASS". Three deliberate behaviour changes:
  * a topical route no longer forces HALT (it sets the exposure profile);
  * an unknown/unsourced formula returns NEEDS_INPUT rather than HALT, so the caller
    can ask instead of stopping;
  * a traditional-use-only indication now returns REFRAME (traditional use is not
    demonstrated efficacy) where v11 returned PASS.

References for the rules encoded here (push through `citation_grounding` when a run
cites them): see `REFERENCES` at the bottom of this module.
"""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# --------------------------------------------------------------------------------------
# Verdict vocabulary (plain strings — v11 callers compare GateVerdict.action to these)
# --------------------------------------------------------------------------------------
PASS = "PASS"
REFRAME = "REFRAME"
HALT = "HALT"
EXPOSURE_MISMATCH = "EXPOSURE_MISMATCH"
NEEDS_INPUT = "NEEDS_INPUT"

#: Most severe first. The gate reports every reason it found, but one action.
VERDICT_PRECEDENCE = (HALT, EXPOSURE_MISMATCH, NEEDS_INPUT, REFRAME, PASS)

#: File the caller should write for each stopping verdict (None = no stop file).
HALT_FILES = {
    HALT: "HALT_provenance.md",
    NEEDS_INPUT: "HALT_provenance.md",       # service mode; interactive mode asks instead
    EXPOSURE_MISMATCH: "HALT_exposure_mismatch.md",
    REFRAME: None,
    PASS: None,
}

# --------------------------------------------------------------------------------------
# Modalities
# --------------------------------------------------------------------------------------
MODALITIES = ("small_molecule", "peptide", "protein_antibody", "oligonucleotide",
              "herbal_formula", "extracellular_vesicle", "cell", "other")

_MODALITY_ALIASES = {
    "small molecule": "small_molecule", "smallmolecule": "small_molecule",
    "nce": "small_molecule", "chemical": "small_molecule", "drug": "small_molecule",
    "peptide": "peptide", "polypeptide": "peptide",
    "antibody": "protein_antibody", "mab": "protein_antibody", "protein": "protein_antibody",
    "biologic": "protein_antibody", "protein_antibody": "protein_antibody",
    "oligo": "oligonucleotide", "oligonucleotide": "oligonucleotide",
    "sirna": "oligonucleotide", "aso": "oligonucleotide", "antisense": "oligonucleotide",
    "herbal": "herbal_formula", "herbal_formula": "herbal_formula", "formula": "herbal_formula",
    "tcm": "herbal_formula", "decoction": "herbal_formula",
    "ev": "extracellular_vesicle", "exosome": "extracellular_vesicle",
    "extracellular_vesicle": "extracellular_vesicle", "exosomes": "extracellular_vesicle",
    "cell": "cell", "cell_therapy": "cell", "car-t": "cell", "cart": "cell",
    "car_t": "cell", "stem_cell": "cell",
}


def normalize_modality(modality: Optional[str]) -> str:
    m = _norm(modality)
    if not m:
        return "unknown"
    if m in MODALITIES:
        return m
    return _MODALITY_ALIASES.get(m, m)


# --------------------------------------------------------------------------------------
# Routes — the gate now classifies the route FOR THE EXPOSURE MODEL, not to stop a run
# --------------------------------------------------------------------------------------
#: Legacy route label -> the vocabulary `moa_lib.exposure` is specified in (design §4.4).
ROUTE_TO_EXPOSURE = {
    "topical": "topical_skin", "external": "topical_skin", "topical_skin": "topical_skin",
    "transdermal": "transdermal", "oral": "oral", "po": "oral",
    "subcutaneous": "subcutaneous", "sc": "subcutaneous",
    "intramuscular": "intramuscular", "im": "intramuscular",
    "intravenous": "intravenous", "iv": "intravenous",
    "inhaled": "inhaled", "inhalation": "inhaled", "intranasal": "intranasal",
    "ophthalmic": "ophthalmic", "eye": "ophthalmic", "otic": "otic",
    "buccal": "buccal_sublingual", "sublingual": "buccal_sublingual",
    "rectal": "rectal", "vaginal": "vaginal", "intra_articular": "intra_articular",
    "intrathecal": "intrathecal",
}


def normalize_route(route: Optional[str]) -> str:
    r = _norm(route)
    if not r:
        return "unknown"
    return ROUTE_TO_EXPOSURE.get(r, r)


# --------------------------------------------------------------------------------------
# FORMULA_REF — a LIST of sourced variants per formula (kernel design §8.1 R3)
# --------------------------------------------------------------------------------------
# Compositions of classical formulas differ between sources, so there is no single
# canonical list. Each variant carries its own source and `source_kind`:
#     classical | pharmacopoeia | publication | user_provided
# A provided list matching ANY sourced variant passes, and the result names the variant.
# A list matching none is a mismatch and HALTs (this is the Session-9 failure).
#
# ZERO FABRICATION: a variant whose composition cannot be sourced is NOT added here.
# To add one, cite the text/pharmacopoeia entry it comes from in `source`.
FORMULA_REF = {
    "qibai san": {
        "aliases": ["七白散", "七白膏", "洗面七白散", "qibai san", "qi bai san"],
        "route": "topical",                        # 外用 — face wash / mask
        "route_source": "太平聖惠方 (七白膏); 永類鈐方 (洗面七白散) — 外用美白祛斑",
        "route_evidence_tier": "E1",               # named in the classical source itself
        "traditional_indications": ["skin whitening", "freckle/melasma (祛斑)",
                                    "facial cosmetic", "hyperpigmentation"],
        "note": "Topical cosmetic mask; sources warn it is external-use, not taken internally.",
        "variants": [
            {
                "variant_id": "qibai_7herb_taiping_yonglei",
                "label": "七白膏 / 洗面七白散 (seven whites, 7 herbs)",
                "herb_count": 7,
                "herbs": [("白蘞", "ampelopsis"), ("白朮", "atractylodes"),
                          ("白牽牛", "pharbitis"), ("白芍藥", "paeonia"),
                          ("白僵蠶", "bombyx"), ("白芷", "angelica"),
                          ("白附子", "typhonium")],
                "source": "太平聖惠方 (七白膏); 永類鈐方 (洗面七白散) — 外用美白祛斑",
                "source_kind": "classical",
            },
        ],
    },
}


# --------------------------------------------------------------------------------------
# Identity requirements per modality (kernel design §8.1 R2)
# --------------------------------------------------------------------------------------
# The module VERIFIES WHAT IT CAN FROM SUPPLIED EVIDENCE and REPORTS WHAT IS MISSING.
# It performs no network access: the run script fetches, persists to `data/`, and passes
# the records in. Input contract per modality (`evidence` argument of verify_identity):
#
# small_molecule / peptide:
#   {"pubchem": {"cid": "60823", "inchikey": "XUKUURHRXDUEBC-KAYWLYCHSA-N",
#                "is_parent": True},
#    "chembl":  {"chembl_id": "CHEMBL1487", "inchikey": "XUKUURHRXDUEBC-KAYWLYCHSA-N",
#                "parent_chembl_id": "CHEMBL1487", "molecule_type": "Small molecule"}}
#   A source may instead be {"status": "not_found"} / {"status": "fetch_failed"} —
#   a recorded negative, which is NOT the same as not having looked.
#   Verification = InChIKey **parent** skeleton (first block) agreeing across >=2
#   independent sources. Records that are not the parent (salt/hydrate, i.e.
#   chembl.parent_chembl_id != chembl.chembl_id, or is_parent=False) must be resolved
#   to their parent first — the module asks for that instead of HALTing, because a
#   hydrate record is not a wrong molecule. (Real case: PubChem tacrolimus
#   QJJXYPPXXYFBGM-… vs ChEMBL CHEMBL3989887 monohydrate NWJQLQGQZSIBAF-…, whose
#   parent CHEMBL269732 agrees with PubChem.)
#   A record that says nothing about parentage is taken at face value as the parent —
#   PubChem name lookups resolve to the parent compound — so assert `is_parent: False`
#   or carry `parent_chembl_id` whenever the stored record is a salt/hydrate/mixture.
#
# protein_antibody:
#   {"inn": "dupilumab", "chembl": {"chembl_id": "CHEMBL...", "molecule_type": "Antibody"},
#    "uniprot_target": ["P24394"], "label": {"source": "FDA label / DailyMed set id"}}
#
# oligonucleotide:
#   {"sequence": "GUAACAAAGGUGCUCA...", "backbone": "siRNA, 2'-OMe/2'-F, phosphorothioate,
#    triantennary GalNAc", "target_transcript": {"gene": "PCSK9", "refseq": "NM_174936",
#    "source": "sequence alignment, <tool/PMID>"}}
#
# cell:
#   {"cell_type": "autologous T cell", "source": "patient apheresis (autologous)",
#    "construct": {"car_target": "CD19", "vector": "lentiviral", "source": "label/PMID"}}
#
# extracellular_vesicle:
#   {"source_cell_type": "human adipose-derived stem cell (ADSC)",
#    "isolation_method": "differential ultracentrifugation + size-exclusion chromatography",
#    "positive_markers": ["CD9", "CD81", "TSG101"],
#    "negative_markers": ["calnexin"],
#    "particle_characterisation": ["TEM", "NTA"]}
#
# herbal_formula: composition is the identity check — pass `provided_herbs` and
#   `composition_source` instead of `evidence`.
IDENTITY_REQUIREMENTS = {
    "small_molecule": ("InChIKey parent from PubChem", "InChIKey parent from ChEMBL"),
    "peptide": ("InChIKey parent from PubChem", "InChIKey parent from ChEMBL",
                "or the protein_antibody evidence set (INN + ChEMBL biotherapeutic + "
                "UniProt target + label)"),
    "protein_antibody": ("INN (international nonproprietary name)",
                         "ChEMBL biotherapeutic record",
                         "UniProt accession of the target",
                         "approved label reference"),
    "oligonucleotide": ("nucleotide sequence", "backbone/modification chemistry",
                        "target transcript resolved FROM the sequence (gene + accession + source)"),
    "cell": ("cell type", "source (autologous/allogeneic + tissue)",
             "engineered construct (e.g. CAR target) with its source"),
    "extracellular_vesicle": ("source cell type", "isolation method",
                              ">=3 positive EV proteins incl. >=1 transmembrane and >=1 cytosolic",
                              ">=1 non-EV (negative) marker",
                              ">=1 single-particle characterisation method"),
    "herbal_formula": ("herb list", "a sourced composition variant (classical / "
                       "pharmacopoeia / publication) or an explicit user-provided source"),
}

# --- MISEV minimum-information items required for EV identity ---------------------------
# Chosen set and the reason for each (kernel design §8.4 left this to the builder). These
# are the four MISEV "minimal requirements for defining an EV preparation" reduced to what
# Step 0 can check from a methods description, plus the separation protocol:
MISEV_MIN_ITEMS = {
    "source_cell_type": "what produced the EVs — without it the preparation has no identity "
                        "and cargo/mechanism claims cannot be attributed",
    "isolation_method": "the separation protocol determines what co-isolates; an EV claim "
                        "without it is uninterpretable (also the core of EV-TRACK reporting)",
    "positive_markers": ">=3 EV proteins including >=1 transmembrane/lipid-bound (CD9/CD63/"
                        "CD81/CD37/CD82/ITGB1...) and >=1 cytosolic (TSG101/syntenin-1/ALIX/"
                        "HSP70/flotillin-1...) — the MISEV demonstration that the particles "
                        "are membrane-enclosed vesicles of the expected topology",
    "negative_markers": ">=1 non-EV marker (calnexin/GM130/albumin/ApoA1/ApoB...) — documents "
                        "co-isolate contamination; this is the difference between 'EVs' and "
                        "'a conditioned-medium pellet'",
    "particle_characterisation": ">=1 single-particle method (imaging: TEM/cryo-EM/AFM; or "
                                 "many-particle: NTA/flow cytometry) giving particle number "
                                 "and size distribution. MISEV asks for two complementary "
                                 "techniques, so one is accepted with a note, two is complete",
}
MISEV_TRANSMEMBRANE = {"cd9", "cd63", "cd81", "cd37", "cd82", "cd47", "itgb1", "itga4",
                       "lamp1", "lamp2", "lamp2b", "mhc class i", "hla-a", "hla-drb",
                       "tfrc", "cd71", "gpi-anchored", "cd55", "cd59"}
MISEV_CYTOSOLIC = {"tsg101", "syntenin", "syntenin-1", "sdcbp", "alix", "pdcd6ip",
                   "hsp70", "hspa8", "hsc70", "hsp90", "flotillin", "flotillin-1", "flot1",
                   "flot2", "chmp4b", "actb", "beta-actin", "gapdh", "annexin a2", "anxa2"}
MISEV_NEGATIVE = {"calnexin", "canx", "gm130", "golga2", "albumin", "alb", "apoa1", "apob",
                  "apoa-i", "apob-100", "grp94", "hsp90b1", "cytochrome c", "cycs",
                  "prohibitin", "phb", "ribosomal protein", "argonaute", "ago2",
                  "lipoprotein", "tamm-horsfall", "umod"}
MISEV_IMAGING = {"tem", "cryo-em", "cryoem", "cryo-tem", "sem", "afm", "electron microscopy",
                 "em", "stem"}
MISEV_PARTICLE = MISEV_IMAGING | {"nta", "nanoparticle tracking analysis", "drps", "trps",
                                  "flow cytometry", "nfcm", "imaging flow cytometry",
                                  "single-particle interferometric", "spir", "dls"}


# --------------------------------------------------------------------------------------
# Circularity control (kernel design §8.2 B2)
# --------------------------------------------------------------------------------------
#: Open Targets evidence to strip in leg (i). `known_drug` IS the clinical-precedence
#: datatype: its only datasource is ChEMBL's drug/indication records, i.e. the drug's own
#: development programme feeding its target back in as "disease association".
CIRCULARITY_OT_DATATYPES = ("known_drug",)
CIRCULARITY_OT_DATASOURCES = ("chembl",)

#: Leg (ii) — "the compound's own literature". A stored publication counts when it is
#: ABOUT the compound (title/abstract/MeSH substance) AND is one of these PubMed
#: publication types. Rationale: these are the records a drug's own development programme
#: generates (its trials) or that restate them (reviews of the drug). They are the route
#: by which a drug's own evidence re-enters the disease-gene list through text-mining,
#: which is how a target survived the datatype-only strip in a recent run. Primary
#: research on the *target* (not the drug) is NOT stripped — that is independent biology.
CIRCULARITY_PUBTYPES = (
    # trial family
    "clinical trial", "clinical trial, phase i", "clinical trial, phase ii",
    "clinical trial, phase iii", "clinical trial, phase iv", "randomized controlled trial",
    "controlled clinical trial", "pragmatic clinical trial", "adaptive clinical trial",
    "equivalence trial", "clinical trial protocol", "clinical study",
    # synthesis/restatement family
    "review", "systematic review", "meta-analysis",
)
#: An extra heuristic, flagged separately: PT indexing lags, so a record that registers a
#: trial of the compound (an NCT id in the abstract/metadata) counts as a trial even when
#: no trial publication type is indexed yet.
CIRCULARITY_NCT_RE = re.compile(r"\bNCT\d{8}\b", re.I)


# --------------------------------------------------------------------------------------
# What this module expects from `moa_lib.exposure` (written separately; design §4.4/§8.2 B3)
# --------------------------------------------------------------------------------------
EXPOSURE_INTERFACE = """\
Target-tissue reachability comes from moa_lib.exposure. This gate finds ONE callable there,
by name, in this order:
    reaches_target_tissue | reaches_tissue | target_tissue_reachability | reachability
    | assess_reachability
and calls it with ONLY the keyword arguments its signature accepts, from:
    tissue=<tissue of pathology>, profile=<ExposureProfile>, modality=<normalised modality>,
    route=<normalised exposure route>, formulation=<str|None>
A resolver that takes a `profile` gets one: the caller's, or else one this gate builds with
`exposure.herbal_formula_profile(...)` (herbal formulas, so the formula's classical route
source carries its E1 compartment) or `exposure.build_profile(modality, route, formulation)`.

The result may be a Reachability-like object, a mapping, or the `(is_mismatch, Reachability)`
tuple that `exposure.exposure_mismatch()` returns. Fields read (aliases listed):
    verdict | level        'reachable_direct' | 'reachable_systemic' | 'as_is' | 'dds_enabled'
                           | 'not_deliverable_to_target_tissue' | 'not_assessable'
    reachable              bool | None — derived from the verdict when absent, and vice versa
    route_compartments | compartments | primary_compartments   list[str]
    target_compartment     str | None
    via                    'direct' | 'systemic' | ''
    sources | source       FieldSource-like (.citation/.kind/.detail), str, or list of either
    provisional            bool — a rule-of-thumb-only profile; cannot alone support a
                           systemic or responder claim
    evidence_tier | tier   'E0'..'E4' (E4 is equivalent to provisional)
    rationale | reason | note   str | list[str]
    dds_bridgeable, dds_candidates   optional. moa_lib.exposure does not model delivery
                           systems, so the gate also accepts these from the caller
                           (route_feasibility / delivery_paths) and merges them in.
Only `not_deliverable_to_target_tissue` (or reachable=False) stops the run: Step 0 then
returns EXPOSURE_MISMATCH. `not_assessable` is NEVER a pass — it yields NEEDS_INPUT.
"""

_EXPOSURE_RESOLVER_NAMES = ("reaches_target_tissue", "reaches_tissue",
                            "target_tissue_reachability", "reachability",
                            "assess_reachability")

#: Reachability verdicts, from every vocabulary this gate accepts, that mean "reached".
_REACHABLE_LEVELS = ("reachable_direct", "reachable_systemic", "as_is", "dds_enabled")


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _norm(s) -> str:
    return (s or "").strip().lower() if isinstance(s, str) else ("" if s is None else str(s).strip().lower())


def _as_list(x) -> list:
    if x is None:
        return []
    if isinstance(x, (list, tuple, set)):
        return list(x)
    return [x]


def _get(obj: Any, *names, default=None):
    """Read a field from an object or a mapping, trying several names."""
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    return default


def _lookup(name: str) -> Optional[dict]:
    n = _norm(name)
    for key, rec in FORMULA_REF.items():
        if n == key or any(_norm(a) in n or n in _norm(a) for a in rec["aliases"]):
            return rec
    return None


def _inchikey_skeleton(key: str) -> str:
    """First InChIKey block — the connectivity (skeleton) hash, i.e. the parent identity."""
    k = (key or "").strip().upper()
    return k.split("-")[0] if k else ""


# --------------------------------------------------------------------------------------
# 1. Composition (herbal formulas) — several sourced variants
# --------------------------------------------------------------------------------------
@dataclass
class CompositionCheck:
    # --- v11 fields, unchanged order so legacy positional construction still works ---
    known: bool
    provided_count: int
    authentic_count: Optional[int]
    matched: list = field(default_factory=list)
    missing: list = field(default_factory=list)     # in the variant, absent from provided
    extra: list = field(default_factory=list)       # in provided, not in the variant
    verdict: str = "unknown"
    # match | mismatch | unknown | unsourceable | user_provided_variant
    # | sourced_external | not_applicable
    reasons: list = field(default_factory=list)
    # --- v12 additions ---
    matched_variant: Optional[str] = None           # variant_id
    matched_variant_label: Optional[str] = None
    variant_source: Optional[str] = None
    variant_source_kind: Optional[str] = None       # classical|pharmacopoeia|publication|user_provided
    candidate_variants: list = field(default_factory=list)  # per-variant diff when nothing matched

    @property
    def is_user_provided(self) -> bool:
        return self.verdict == "user_provided_variant"

    @property
    def passes(self) -> bool:
        return self.verdict in ("match", "user_provided_variant", "sourced_external",
                                "not_applicable")


def _diff_against_variant(provided_herbs: list, variant: dict) -> dict:
    matched, extra, auth_hit = [], [], set()
    for h in provided_herbs:
        hl = _norm(h)
        hit = None
        for i, (cn, lat) in enumerate(variant["herbs"]):
            if cn in str(h) or (lat and lat in hl):
                hit = i
                break
        if hit is not None:
            matched.append(h)
            auth_hit.add(hit)
        else:
            extra.append(h)
    missing = [f"{cn} ({lat})" for i, (cn, lat) in enumerate(variant["herbs"]) if i not in auth_hit]
    reasons = []
    count = variant.get("herb_count", len(variant["herbs"]))
    if len(provided_herbs) != count:
        reasons.append(f"herb count {len(provided_herbs)} != {count} in variant "
                       f"'{variant['variant_id']}'")
    if missing:
        reasons.append(f"missing herbs of '{variant['variant_id']}': {', '.join(missing)}")
    if extra:
        reasons.append(f"herbs not in '{variant['variant_id']}': {', '.join(str(e) for e in extra)}")
    return {"variant_id": variant["variant_id"], "label": variant.get("label"),
            "source": variant.get("source"), "source_kind": variant.get("source_kind"),
            "herb_count": count, "matched": matched, "missing": missing, "extra": extra,
            "reasons": reasons,
            "is_match": not missing and not extra and len(provided_herbs) == count}


def validate_composition(name: str, provided_herbs: list,
                         *, composition_source: Optional[dict] = None) -> CompositionCheck:
    """Match a provided herb list against the SOURCED VARIANTS of a formula.

    `composition_source` (optional) declares where the provided list comes from:
        {"kind": "classical"|"pharmacopoeia"|"publication"|"user_provided"|"unsourceable",
         "source": "<citation, or the lab's name for a user-provided preparation>",
         "label": "<optional variant label>"}

    A list matching any sourced variant -> verdict "match", naming the variant.
    A list matching none -> "mismatch" (HALT) unless it is declared `user_provided`,
    in which case it is recorded as a `user_provided_variant` with the lab as its source
    and the run proceeds.
    """
    prov = list(provided_herbs or [])
    src_kind = _norm((composition_source or {}).get("kind"))
    src_text = (composition_source or {}).get("source") or ""
    rec = _lookup(name)

    if src_kind == "unsourceable":
        return CompositionCheck(
            bool(rec), len(prov), None, verdict="unsourceable",
            reasons=[f"composition of '{name}' could not be sourced"
                     + (f" ({src_text})" if src_text else "")
                     + " — the object of study is unverified; do not analyse it"])

    if not rec:
        # Formula not in the reference table.
        if src_kind == "user_provided" and prov:
            return CompositionCheck(
                False, len(prov), len(prov), matched=list(prov), verdict="user_provided_variant",
                variant_source=src_text or "user-provided (no source named)",
                variant_source_kind="user_provided",
                matched_variant_label=(composition_source or {}).get("label")
                or f"{name} — user-provided preparation",
                reasons=[f"'{name}' is not in the provenance reference; composition recorded as "
                         f"the user's/lab's own preparation (source: "
                         f"{src_text or 'not named'}). The report must state that the composition "
                         f"is the lab's, not a classical one."])
        if src_kind in ("classical", "pharmacopoeia", "publication") and prov and src_text:
            return CompositionCheck(
                False, len(prov), len(prov), matched=list(prov), verdict="sourced_external",
                variant_source=src_text, variant_source_kind=src_kind,
                matched_variant_label=(composition_source or {}).get("label") or name,
                reasons=[f"'{name}' is not in the module's reference table, but the composition "
                         f"is sourced ({src_kind}: {src_text}) — proceeding, and the variant "
                         f"should be added to FORMULA_REF."])
        return CompositionCheck(
            False, len(prov), None, verdict="unknown",
            reasons=[f"'{name}' not in the provenance reference and no composition source was "
                     f"supplied — cannot verify the object of study. Needed: the classical/"
                     f"pharmacopoeia text (or publication) the composition comes from, or an "
                     f"explicit statement that it is the lab's own preparation."])

    variants = rec.get("variants") or []
    diffs = [_diff_against_variant(prov, v) for v in variants]
    hit = next((d for d in diffs if d["is_match"]), None)
    if hit:
        return CompositionCheck(
            True, len(prov), hit["herb_count"], matched=hit["matched"], verdict="match",
            reasons=[f"matches sourced variant '{hit['variant_id']}' "
                     f"({hit['label']}; source: {hit['source']})"],
            matched_variant=hit["variant_id"], matched_variant_label=hit["label"],
            variant_source=hit["source"], variant_source_kind=hit["source_kind"],
            candidate_variants=diffs)

    # nothing matched — closest variant (fewest differences) drives the diff report
    closest = min(diffs, key=lambda d: len(d["missing"]) + len(d["extra"])) if diffs else None
    if src_kind == "user_provided" and prov:
        reasons = [f"composition matches no sourced variant of '{name}'; recorded as the "
                   f"user's/lab's own preparation (source: {src_text or 'not named'}). The report "
                   f"must state that the composition is the lab's, not a classical one."]
        if closest:
            reasons.append("difference vs closest sourced variant — " + "; ".join(closest["reasons"]))
        return CompositionCheck(
            True, len(prov), closest["herb_count"] if closest else None,
            matched=closest["matched"] if closest else list(prov),
            missing=closest["missing"] if closest else [],
            extra=closest["extra"] if closest else [],
            verdict="user_provided_variant", reasons=reasons,
            matched_variant="user_provided_variant",
            matched_variant_label=(composition_source or {}).get("label")
            or f"{name} — user-provided preparation",
            variant_source=src_text or "user-provided (no source named)",
            variant_source_kind="user_provided", candidate_variants=diffs)

    reasons = [f"composition matches none of the {len(variants)} sourced variant(s) of '{name}' "
               f"— this is a different preparation"]
    if closest:
        reasons.extend(closest["reasons"])
    return CompositionCheck(
        True, len(prov), closest["herb_count"] if closest else None,
        matched=closest["matched"] if closest else [],
        missing=closest["missing"] if closest else [],
        extra=closest["extra"] if closest else list(prov),
        verdict="mismatch", reasons=reasons, candidate_variants=diffs)


# --------------------------------------------------------------------------------------
# 2. Route — for the exposure model (no longer a stop decision)
# --------------------------------------------------------------------------------------
class RouteInfo(tuple):
    """`(route, source)` — unpacks like the v11 2-tuple, with v12 fields attached."""

    def __new__(cls, route: str, source: str, *, exposure_route: Optional[str] = None,
                evidence_tier: str = "E4", formulation: Optional[str] = None,
                level: str = "formula_level"):
        obj = tuple.__new__(cls, (route, source))
        obj.route = route
        obj.source = source
        obj.exposure_route = exposure_route or normalize_route(route)
        obj.evidence_tier = evidence_tier
        obj.formulation = formulation
        obj.level = level              # formula_level | compound_level | caller_supplied
        return obj

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (f"RouteInfo(route={self.route!r}, exposure_route={self.exposure_route!r}, "
                f"tier={self.evidence_tier!r}, source={self.source!r})")


def classify_route(name: str, *, route: Optional[str] = None, route_source: Optional[str] = None,
                   formulation: Optional[str] = None) -> RouteInfo:
    """Return the route FOR THE EXPOSURE MODEL. Never a stop decision.

    A caller-supplied route (from the run card / label) wins over the reference table,
    because the same molecule is marketed by several routes (ruxolitinib: oral tablet
    and cream).
    """
    if route:
        return RouteInfo(_norm(route), route_source or "caller-supplied (run card / label)",
                         evidence_tier="E1" if route_source else "E4",
                         formulation=formulation, level="caller_supplied")
    rec = _lookup(name)
    if not rec:
        return RouteInfo("unknown", "not in reference — supply the route from the label or "
                                    "the formula's classical source",
                         evidence_tier="", formulation=formulation, level="unresolved")
    # A formula's route from its classical/pharmacopoeia source is a legitimate E1 source
    # for the compartment and applies to its constituents (kernel design §8.2 B6).
    return RouteInfo(rec["route"], rec["route_source"],
                     evidence_tier=rec.get("route_evidence_tier", "E1"),
                     formulation=formulation, level="formula_level")


# --------------------------------------------------------------------------------------
# 3. Identity verification, per modality
# --------------------------------------------------------------------------------------
@dataclass
class IdentityCheck:
    modality: str
    name: str
    verdict: str = "not_supplied"
    # verified | conflict | unverifiable | insufficient | not_supplied | not_applicable
    evidence_tier: str = ""
    matched_on: list = field(default_factory=list)
    missing: list = field(default_factory=list)      # what the run script must still fetch
    conflicts: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    requirements: tuple = ()
    sources: list = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.verdict in ("verified", "not_applicable")

    @property
    def halts(self) -> bool:
        return self.verdict in ("conflict", "unverifiable")

    @property
    def needs_input(self) -> bool:
        return self.verdict in ("insufficient", "not_supplied")


def _record_status(rec) -> str:
    """'present' | 'not_found' | 'fetch_failed' | 'absent'."""
    if rec is None:
        return "absent"
    st = _norm(_get(rec, "status", default=""))
    if st in ("not_found", "notfound", "none", "missing"):
        return "not_found"
    if st in ("fetch_failed", "failed", "error"):
        return "fetch_failed"
    if isinstance(rec, dict) and ("FETCH_FAILED" in rec or "fetch_failed" in rec):
        return "fetch_failed"
    return "present"


def _verify_small_molecule(name: str, ev: dict, modality: str) -> IdentityCheck:
    chk = IdentityCheck(modality, name, requirements=IDENTITY_REQUIREMENTS.get(modality, ()))
    sources = {k: ev.get(k) for k in ("pubchem", "chembl", "drugbank", "unichem")
               if k in ev}
    if not sources:
        chk.verdict = "not_supplied"
        chk.missing = ["pubchem: InChIKey of the PARENT compound (name/CID lookup)",
                       "chembl: standard_inchi_key of the PARENT molecule "
                       "(follow molecule_hierarchy.parent_chembl_id)"]
        return chk

    keys, unresolved_parents, negatives = {}, [], []
    for src, rec in sources.items():
        st = _record_status(rec)
        if st != "present":
            negatives.append(f"{src}: {st}")
            continue
        key = _get(rec, "inchikey_parent", "parent_inchikey", "inchikey", "standard_inchi_key",
                   default="")
        if not key:
            chk.missing.append(f"{src}: InChIKey missing from the stored record")
            continue
        # is this record the parent?
        parent_id = _get(rec, "parent_chembl_id", "parent_id")
        own_id = _get(rec, "chembl_id", "molecule_chembl_id", "cid", "id")
        is_parent = _get(rec, "is_parent")
        if _get(rec, "inchikey_parent", "parent_inchikey") is not None:
            is_parent = True
        if is_parent is False or (parent_id and own_id and _norm(parent_id) != _norm(own_id)):
            unresolved_parents.append(
                f"{src}: record {own_id} is not the parent "
                f"(parent={parent_id or 'unknown'}) — resolve the parent and re-check")
            continue
        keys[src] = key
        chk.sources.append(f"{src}:{own_id or '?'}={key}")

    skeletons = {src: _inchikey_skeleton(k) for src, k in keys.items()}
    distinct = set(skeletons.values())

    if len(distinct) > 1:
        chk.verdict = "conflict"
        chk.conflicts = [f"InChIKey parent skeletons disagree across sources: "
                         + ", ".join(f"{s}={sk}" for s, sk in sorted(skeletons.items()))]
        chk.notes.append("a skeleton disagreement between parent records means the sources "
                         "describe different molecules — the object of study is mis-specified")
        return chk

    if len(keys) >= 2 and len(distinct) == 1:
        chk.verdict = "verified"
        chk.evidence_tier = "E0"
        skel = next(iter(distinct))
        chk.matched_on = [f"InChIKey parent skeleton {skel} agrees across "
                          f"{', '.join(sorted(keys))}"]
        full = set(keys.values())
        if len(full) > 1:
            chk.notes.append("full InChIKeys differ (stereochemistry/salt/isotope layer): "
                             + ", ".join(f"{s}={k}" for s, k in sorted(keys.items()))
                             + " — same parent skeleton, so identity holds; record which form "
                               "the analysed data refers to")
        if unresolved_parents:
            chk.notes.extend(unresolved_parents)
        return chk

    # could not verify from what was supplied
    if unresolved_parents:
        chk.verdict = "insufficient"
        chk.missing.extend(unresolved_parents)
        if keys:
            chk.notes.append("verified so far: " + ", ".join(f"{s}={k}" for s, k in keys.items()))
        return chk
    if negatives and not keys:
        chk.verdict = "unverifiable"
        chk.conflicts = [f"identity could not be established: {', '.join(negatives)}"]
        chk.notes.append("the lookup was performed and returned nothing — this is not a missing "
                         "fetch but an unidentifiable object of study")
        return chk
    chk.verdict = "insufficient"
    have = ", ".join(sorted(keys)) or "none"
    chk.missing.append(f"a second independent InChIKey parent source (have: {have}; "
                       f"need PubChem AND ChEMBL)")
    if negatives:
        chk.missing.extend(negatives)
    return chk


def _verify_protein(name: str, ev: dict, modality: str) -> IdentityCheck:
    chk = IdentityCheck(modality, name, requirements=IDENTITY_REQUIREMENTS["protein_antibody"])
    inn = _get(ev, "inn", "nonproprietary_name")
    chembl = ev.get("chembl")
    target = _as_list(ev.get("uniprot_target") or ev.get("uniprot"))
    label = ev.get("label") or ev.get("label_source")
    if not any([inn, chembl, target, label]):
        chk.verdict = "not_supplied"
        chk.missing = list(chk.requirements)
        return chk
    if inn:
        chk.matched_on.append(f"INN: {inn}")
    else:
        chk.missing.append("INN (international nonproprietary name)")
    if _record_status(chembl) == "present" and _get(chembl, "chembl_id", "molecule_chembl_id"):
        mtype = _norm(_get(chembl, "molecule_type", default=""))
        cid = _get(chembl, "chembl_id", "molecule_chembl_id")
        chk.matched_on.append(f"ChEMBL record {cid} (molecule_type={mtype or 'unstated'})")
        chk.sources.append(f"chembl:{cid}")
        if mtype and mtype not in ("antibody", "protein", "enzyme", "oligosaccharide", "unknown"):
            chk.notes.append(f"ChEMBL molecule_type '{mtype}' is not a biotherapeutic type — "
                             f"check the record is the right entity")
    else:
        chk.missing.append("ChEMBL biotherapeutic record")
    if target:
        chk.matched_on.append("UniProt target(s): " + ", ".join(str(t) for t in target))
        chk.sources.extend(f"uniprot:{t}" for t in target)
    else:
        chk.missing.append("UniProt accession of the target")
    if _record_status(label) == "present":
        chk.matched_on.append(f"label: {_get(label, 'source', 'id', default=label)}")
    else:
        chk.missing.append("approved label reference (route + mechanism section)")
    chk.verdict = "verified" if not chk.missing else "insufficient"
    chk.evidence_tier = "E1" if chk.verdict == "verified" else ""
    return chk


def _verify_oligo(name: str, ev: dict, modality: str) -> IdentityCheck:
    chk = IdentityCheck(modality, name, requirements=IDENTITY_REQUIREMENTS["oligonucleotide"])
    seq = _get(ev, "sequence", "sequences")
    backbone = _get(ev, "backbone", "chemistry", "backbone_chemistry")
    tx = ev.get("target_transcript") or ev.get("transcript")
    if not any([seq, backbone, tx]):
        chk.verdict = "not_supplied"
        chk.missing = list(chk.requirements)
        return chk
    seqs = [s for s in _as_list(seq) if s]
    if seqs:
        for s in seqs:
            bad = set(re.sub(r"[^A-Za-z]", "", str(s)).upper()) - set("ACGTUN")
            if bad:
                chk.conflicts.append(f"sequence contains non-nucleotide characters: "
                                     f"{''.join(sorted(bad))}")
        chk.matched_on.append(f"sequence ({len(seqs)} strand(s), "
                              f"{'/'.join(str(len(re.sub(r'[^A-Za-z]', '', str(s)))) for s in seqs)} nt)")
    else:
        chk.missing.append("nucleotide sequence")
    if backbone:
        chk.matched_on.append(f"backbone chemistry: {backbone}")
    else:
        chk.missing.append("backbone/modification chemistry (e.g. phosphorothioate, 2'-MOE, "
                           "siRNA duplex, GalNAc conjugate)")
    if _record_status(tx) == "present":
        gene = _get(tx, "gene", "gene_symbol")
        acc = _get(tx, "refseq", "accession", "ensembl", "transcript")
        src = _get(tx, "source", "method")
        if gene and acc and src:
            chk.matched_on.append(f"target transcript {gene} / {acc} resolved from the sequence "
                                  f"({src})")
            chk.sources.append(f"transcript:{acc}")
        else:
            chk.missing.append("target transcript resolved FROM the sequence: needs gene symbol, "
                               "transcript accession AND the resolution source/method "
                               f"(have gene={gene or '-'}, accession={acc or '-'}, source={src or '-'})")
    else:
        chk.missing.append("target transcript resolved FROM the sequence (gene + accession + source)")
    if chk.conflicts:
        chk.verdict = "conflict"
        return chk
    chk.verdict = "verified" if not chk.missing else "insufficient"
    chk.evidence_tier = "E0" if chk.verdict == "verified" else ""
    return chk


def _verify_cell(name: str, ev: dict, modality: str) -> IdentityCheck:
    chk = IdentityCheck(modality, name, requirements=IDENTITY_REQUIREMENTS["cell"])
    cell_type = _get(ev, "cell_type", "celltype")
    source = _get(ev, "source", "origin")
    construct = ev.get("construct") or ev.get("engineered_construct")
    if not any([cell_type, source, construct]):
        chk.verdict = "not_supplied"
        chk.missing = list(chk.requirements)
        return chk
    if cell_type:
        chk.matched_on.append(f"cell type: {cell_type}")
    else:
        chk.missing.append("cell type")
    if source:
        chk.matched_on.append(f"source: {source}")
    else:
        chk.missing.append("source (autologous/allogeneic + tissue)")
    if _record_status(construct) == "present":
        tgt = _get(construct, "car_target", "target", "transgene")
        csrc = _get(construct, "source", "label", "pmid")
        if tgt:
            chk.matched_on.append(f"engineered construct: {tgt}"
                                  + (f" ({_get(construct, 'vector', default='')})"
                                     if _get(construct, "vector") else ""))
            chk.sources.append(f"construct:{tgt}")
        else:
            chk.missing.append("engineered construct target (e.g. CAR target gene)")
        if not csrc:
            chk.missing.append("source for the construct (label or PMID)")
    else:
        chk.missing.append("engineered construct (e.g. CAR target) with its source")
    chk.verdict = "verified" if not chk.missing else "insufficient"
    chk.evidence_tier = "E1" if chk.verdict == "verified" else ""
    return chk


def _any_in(items: Iterable, vocab: set) -> list:
    out = []
    for it in items:
        s = _norm(it)
        if any(v in s for v in vocab):
            out.append(it)
    return out


def _verify_ev(name: str, ev: dict, modality: str) -> IdentityCheck:
    """EV identity against the MISEV minimum-information items in MISEV_MIN_ITEMS."""
    chk = IdentityCheck(modality, name, requirements=IDENTITY_REQUIREMENTS["extracellular_vesicle"])
    src_cell = _get(ev, "source_cell_type", "source_cell", "cell_source")
    iso = _get(ev, "isolation_method", "isolation", "separation_method")
    pos = _as_list(ev.get("positive_markers") or ev.get("markers"))
    neg = _as_list(ev.get("negative_markers") or ev.get("non_ev_markers"))
    part = _as_list(ev.get("particle_characterisation") or ev.get("particle_characterization")
                    or ev.get("single_vesicle"))
    if not any([src_cell, iso, pos, neg, part]):
        chk.verdict = "not_supplied"
        chk.missing = [f"{k}: {v}" for k, v in MISEV_MIN_ITEMS.items()]
        return chk

    if src_cell:
        chk.matched_on.append(f"source cell type: {src_cell}")
    else:
        chk.missing.append(f"source_cell_type — {MISEV_MIN_ITEMS['source_cell_type']}")
    if iso:
        chk.matched_on.append(f"isolation method: {iso}")
    else:
        chk.missing.append(f"isolation_method — {MISEV_MIN_ITEMS['isolation_method']}")

    tm = _any_in(pos, MISEV_TRANSMEMBRANE)
    cyt = _any_in(pos, MISEV_CYTOSOLIC)
    if len(pos) >= 3 and tm and cyt:
        chk.matched_on.append(f"positive markers ({len(pos)}): transmembrane {tm}, cytosolic {cyt}")
    else:
        chk.missing.append(
            f"positive_markers — have {len(pos)} ({', '.join(str(p) for p in pos) or 'none'}); "
            f"transmembrane={'yes' if tm else 'NO'}, cytosolic={'yes' if cyt else 'NO'}. "
            f"{MISEV_MIN_ITEMS['positive_markers']}")
    if neg:
        unknown_neg = [n for n in neg if not _any_in([n], MISEV_NEGATIVE)]
        chk.matched_on.append(f"negative (non-EV) markers: {', '.join(str(n) for n in neg)}")
        if unknown_neg:
            chk.notes.append("negative markers not in the MISEV non-EV list (check they are "
                             f"co-isolate markers): {', '.join(str(n) for n in unknown_neg)}")
    else:
        chk.missing.append(f"negative_markers — {MISEV_MIN_ITEMS['negative_markers']}")
    known_part = _any_in(part, MISEV_PARTICLE)
    if known_part:
        chk.matched_on.append(f"particle characterisation: {', '.join(str(p) for p in known_part)}")
        if len(set(_norm(p) for p in known_part)) < 2 or not _any_in(part, MISEV_IMAGING):
            chk.notes.append("MISEV asks for two complementary single-particle techniques, one of "
                             "them close-up imaging (TEM/cryo-EM/AFM) — reported set is below that; "
                             "state it as a reporting limitation")
    else:
        chk.missing.append(f"particle_characterisation — {MISEV_MIN_ITEMS['particle_characterisation']}")

    chk.verdict = "verified" if not chk.missing else "insufficient"
    # An EV preparation is characterised, never structurally identified: its identity
    # evidence tops out at E1 (reported measurements), and cargo/mechanism claims are
    # capped at E2 elsewhere (kernel design §8.1 R2).
    chk.evidence_tier = "E1" if chk.verdict == "verified" else ""
    chk.notes.append("EV runs are hypothesis-level (T3): characterisation establishes the "
                     "preparation, not a mechanism; cargo claims are E2 at most")
    return chk


def _verify_herbal(name: str, comp: CompositionCheck) -> IdentityCheck:
    chk = IdentityCheck("herbal_formula", name,
                        requirements=IDENTITY_REQUIREMENTS["herbal_formula"])
    v = comp.verdict
    if v in ("match", "sourced_external"):
        chk.verdict = "verified"
        chk.evidence_tier = "E1"
        chk.matched_on = [f"composition variant '{comp.matched_variant or comp.matched_variant_label}' "
                          f"(source: {comp.variant_source})"]
    elif v == "user_provided_variant":
        chk.verdict = "verified"
        chk.evidence_tier = "user_provided"
        chk.matched_on = [f"user-provided composition (source: {comp.variant_source})"]
        chk.notes.append("composition is the user's/lab's own preparation, not a classical one — "
                         "the report must say so")
    elif v in ("mismatch", "unsourceable"):
        chk.verdict = "unverifiable"
        chk.conflicts = list(comp.reasons)
    else:  # unknown
        chk.verdict = "insufficient"
        chk.missing = list(comp.reasons)
    return chk


def verify_identity(modality: Optional[str], name: str, evidence: Optional[dict] = None, *,
                    provided_herbs: Optional[list] = None,
                    composition_source: Optional[dict] = None) -> IdentityCheck:
    """Verify the object of study's identity from SUPPLIED evidence.

    No network access: the run script fetches and persists records to `data/`, then passes
    them here. The check reports what it verified and what is still missing
    (`IdentityCheck.missing`), so the caller knows exactly what to fetch next.
    """
    mod = normalize_modality(modality)
    ev = dict(evidence or {})
    if mod == "herbal_formula":
        return _verify_herbal(name, validate_composition(name, provided_herbs or [],
                                                         composition_source=composition_source))
    if mod in ("small_molecule", "peptide"):
        chk = _verify_small_molecule(name, ev, mod)
        if mod == "peptide" and chk.verdict in ("not_supplied", "insufficient"):
            # a peptide may be identified as a biotherapeutic instead of by InChIKey
            alt = _verify_protein(name, ev, mod)
            if alt.verdict == "verified":
                alt.notes.append("identified via the biotherapeutic evidence set; no InChIKey "
                                 "parent match available for this peptide")
                return alt
        return chk
    if mod == "protein_antibody":
        return _verify_protein(name, ev, mod)
    if mod == "oligonucleotide":
        return _verify_oligo(name, ev, mod)
    if mod == "cell":
        return _verify_cell(name, ev, mod)
    if mod == "extracellular_vesicle":
        return _verify_ev(name, ev, mod)
    chk = IdentityCheck(mod, name, verdict="not_supplied")
    chk.missing = [f"modality not recognised ('{modality}') — one of {', '.join(MODALITIES)} "
                   f"is required before identity can be verified"]
    return chk


# --------------------------------------------------------------------------------------
# 4. Indication plausibility — four values
# --------------------------------------------------------------------------------------
INDICATION_STATUSES = ("approved", "trialled", "literature_supported", "none", "unknown")

_LEGACY_INDICATION = {
    "approved": "established", "trialled": "established",
    "literature_supported": "established", "none": "novel/implausible", "unknown": "unknown",
}


class IndicationResult(tuple):
    """`(legacy_status, why)` — unpacks like the v11 2-tuple, with the v12 fields attached.

    `status` is one of INDICATION_STATUSES; `legacy_status` preserves the v11 vocabulary
    ("established" / "novel/implausible" / "unknown") so existing callers keep working.
    """

    def __new__(cls, status: str, why: str, *, evidence_tier: str = "",
                traditional_use: bool = False, traditional_source: str = "",
                user_claims: Optional[list] = None, supporting: Optional[list] = None,
                ungrounded: Optional[list] = None):
        legacy = _LEGACY_INDICATION.get(status, "unknown")
        if status == "none" and traditional_use:
            legacy = "established"       # v11 called a traditional-indication match "established"
        obj = tuple.__new__(cls, (legacy, why))
        obj.status = status
        obj.legacy_status = legacy
        obj.why = why
        obj.evidence_tier = evidence_tier
        obj.traditional_use = traditional_use
        obj.traditional_source = traditional_source
        obj.user_claims = list(user_claims or [])
        obj.supporting = list(supporting or [])
        obj.ungrounded = list(ungrounded or [])
        return obj

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"IndicationResult(status={self.status!r}, tier={self.evidence_tier!r})"


def indication_plausibility(name: str, disease: str, *,
                            evidence: Optional[dict] = None) -> IndicationResult:
    """Four-value indication plausibility (kernel design §4.6).

    `evidence` (all optional, all lists of dicts):
        {"approved":   [{"indication": "...", "source": "FDA label ..."}],
         "trialled":   [{"nct": "NCT01234567", "phase": 3, "source": "..."}],
         "literature": [{"pmid": "12345678", "grounded": True, "claim": "..."}],
         "user_claim": [{"statement": "our lab sees an effect", "published": False}]}

    Rules:
      * approved  > trialled > literature_supported > none
      * a literature entry counts only when `grounded` is True — i.e. it passed
        `citation_grounding` (the PMID resolves AND its abstract supports this claim).
      * a user's statement is recorded as a user-provided claim and NEVER as E1. It is
        promoted to the literature leg only when it carries a grounded PMID.
      * a traditional (classical-source) indication is recorded separately: it is
        documented use, not demonstrated efficacy, so it does not by itself lift the
        status above "none".
    """
    ev = dict(evidence or {})
    rec = _lookup(name)
    d = _norm(disease)

    traditional, trad_src = False, ""
    if rec:
        for ind in rec.get("traditional_indications", []):
            if _norm(ind) and (_norm(ind) in d or d in _norm(ind)):
                traditional, trad_src = True, f"traditional indication '{ind}' ({rec['route_source']})"
                break

    approved = [e for e in _as_list(ev.get("approved")) if e]
    trialled = [e for e in _as_list(ev.get("trialled") or ev.get("trials")) if e]
    lit_all = [e for e in _as_list(ev.get("literature")) if e]
    user_claims = [e for e in _as_list(ev.get("user_claim") or ev.get("user_claims")) if e]

    # a published + grounded user claim is literature; an unpublished one never is
    promoted = []
    for u in user_claims:
        if _get(u, "pmid", "doi") and bool(_get(u, "grounded", default=False)):
            promoted.append(u)
    lit_all = lit_all + promoted
    grounded = [e for e in lit_all if bool(_get(e, "grounded", default=False))]
    ungrounded = [e for e in lit_all if not bool(_get(e, "grounded", default=False))]

    def _src(entries, *keys):
        out = []
        for e in entries:
            out.append(" ".join(str(_get(e, k, default="")) for k in keys).strip() or str(e))
        return out

    if approved:
        why = (f"approved for '{disease}' or its class — "
               + "; ".join(_src(approved, "indication", "source")))
        return IndicationResult("approved", why, evidence_tier="E0", traditional_use=traditional,
                                traditional_source=trad_src, user_claims=user_claims,
                                supporting=approved, ungrounded=ungrounded)
    if trialled:
        why = (f"trialled in '{disease}' — " + "; ".join(_src(trialled, "nct", "phase", "source")))
        return IndicationResult("trialled", why, evidence_tier="E1", traditional_use=traditional,
                                traditional_source=trad_src, user_claims=user_claims,
                                supporting=trialled, ungrounded=ungrounded)
    if grounded:
        why = (f"grounded published efficacy evidence in '{disease}' — "
               + "; ".join(_src(grounded, "pmid", "claim")))
        return IndicationResult("literature_supported", why, evidence_tier="E1",
                                traditional_use=traditional, traditional_source=trad_src,
                                user_claims=user_claims, supporting=grounded,
                                ungrounded=ungrounded)

    bits = [f"no approval, trial or grounded publication supports '{name}' in '{disease}'"]
    if traditional:
        bits.append(f"documented traditional use: {trad_src} — traditional use is documented use, "
                    f"not demonstrated efficacy")
    elif rec:
        bits.append("traditional use is: " + ", ".join(rec.get("traditional_indications", []) or ["-"]))
    if user_claims:
        bits.append("user-provided claim(s) recorded and reported as such (never E1): "
                    + "; ".join(str(_get(u, "statement", default=u)) for u in user_claims))
    if ungrounded:
        bits.append(f"{len(ungrounded)} cited publication(s) did not pass citation grounding and "
                    f"cannot count as E1")
    bits.append("label the run an explicit repurposing hypothesis")
    return IndicationResult("none", " — ".join(bits), evidence_tier="",
                            traditional_use=traditional, traditional_source=trad_src,
                            user_claims=user_claims, supporting=[], ungrounded=ungrounded)


# --------------------------------------------------------------------------------------
# 5. Exposure — route vs the tissue of pathology (consumes moa_lib.exposure)
# --------------------------------------------------------------------------------------
@dataclass
class ExposureCheck:
    assessed: bool = False
    tissue: Optional[str] = None
    route: str = "unknown"
    modality: str = "unknown"
    formulation: Optional[str] = None
    reachable: Optional[bool] = None
    level: str = "not_assessed"
    # reachable_direct | reachable_systemic | as_is | dds_enabled
    # | not_deliverable_to_target_tissue | not_assessable | not_assessed
    compartments: list = field(default_factory=list)
    dds_bridgeable: bool = False
    dds_candidates: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    evidence_tier: str = ""
    reasons: list = field(default_factory=list)
    resolver: str = ""
    target_compartment: Optional[str] = None
    via: str = ""
    provisional: bool = False

    @property
    def mismatch(self) -> bool:
        return self.level == "not_deliverable_to_target_tissue" or self.reachable is False


def _load_exposure_resolver() -> tuple:
    """(callable, name) from moa_lib.exposure, or (None, error_message). Import-guarded:
    moa_lib.exposure is a separate module and may not be present yet."""
    try:
        from . import exposure as _exposure           # noqa: WPS433 (deliberate local import)
    except Exception as exc:                           # ImportError and anything it raises
        return None, (f"moa_lib.exposure is unavailable ({type(exc).__name__}: {exc}). "
                      f"Pass `reachability=` or `exposure_resolver=` instead.\n"
                      + EXPOSURE_INTERFACE)
    for nm in _EXPOSURE_RESOLVER_NAMES:
        fn = getattr(_exposure, nm, None)
        if callable(fn):
            return fn, f"moa_lib.exposure.{nm}"
    return None, ("moa_lib.exposure was imported but exposes none of "
                  + ", ".join(_EXPOSURE_RESOLVER_NAMES) + ".\n" + EXPOSURE_INTERFACE)


def _wants_param(fn, name: str) -> bool:
    """Does this resolver take an explicitly named parameter `name`?

    Explicit only: a `**kwargs` resolver is not assumed to want an ExposureProfile, so the
    gate does not build one it may not use.
    """
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _call_resolver(fn, **kwargs):
    """Call the exposure resolver with only the kwargs its signature accepts."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**kwargs)
    params = sig.parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(**kwargs)
    accepted = {k: v for k, v in kwargs.items() if k in params}
    return fn(**accepted)


def _source_text(s) -> str:
    """Render one source: a FieldSource-like object, a mapping, or a plain string."""
    cit = _get(s, "citation", "source", "id")
    if cit:
        kind = _get(s, "kind", "source_kind", default="")
        detail = _get(s, "detail", "note", default="")
        return " ".join(p for p in (f"[{kind}]" if kind else "", str(cit),
                                    f"— {detail}" if detail else "") if p)
    return str(s)


def _normalise_reachability(raw, chk: ExposureCheck) -> ExposureCheck:
    # exposure.exposure_mismatch() returns (is_mismatch, Reachability)
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[0], bool):
        raw = raw[1]

    level = _norm(_get(raw, "verdict", "level", "feasibility", default="")) or ""
    reachable = _get(raw, "reachable", "is_reachable")
    comp = _as_list(_get(raw, "route_compartments", "compartments", "primary_compartments",
                         default=[]))
    dds_b = bool(_get(raw, "dds_bridgeable", "bridgeable", default=False))
    dds_c = _as_list(_get(raw, "dds_candidates", "dds", default=[]))
    srcs = _as_list(_get(raw, "sources", "source", default=[]))
    tier = _get(raw, "evidence_tier", "tier", default="") or ""
    reason = _get(raw, "rationale", "reason", "note", "notes", default="")
    provisional = bool(_get(raw, "provisional", default=False))

    if not level:
        if reachable is True:
            level = "as_is"
        elif reachable is False:
            level = "not_deliverable_to_target_tissue"
        else:
            level = "not_assessable"
    if reachable is None:
        if level in _REACHABLE_LEVELS:
            reachable = True
        elif level == "not_deliverable_to_target_tissue":
            reachable = False
    # `not_assessable` is never a pass, whatever `reachable` says
    if level == "not_assessable":
        reachable = None

    chk.assessed = level not in ("not_assessable", "not_assessed")
    chk.level = level
    chk.reachable = reachable
    chk.compartments = [str(c) for c in comp]
    chk.dds_bridgeable = dds_b or level == "dds_enabled"
    chk.dds_candidates = [str(c) for c in dds_c]
    chk.sources = [_source_text(s) for s in srcs]
    chk.evidence_tier = str(tier)
    chk.target_compartment = _get(raw, "target_compartment", "compartment")
    chk.via = str(_get(raw, "via", default="") or "")
    chk.provisional = provisional or str(tier).upper() == "E4"
    for r in _as_list(reason):
        if r:
            chk.reasons.append(str(r))
    return chk


def _build_profile(modality: str, route: str, formulation: Optional[str],
                   route_source: str = "") -> tuple:
    """Build an ExposureProfile for a resolver that needs one. -> (profile, note)

    Import-guarded, like the resolver itself. For a herbal formula the formula-level route
    from its classical/pharmacopoeia source is a legitimate E1 compartment source
    (kernel design §8.2 B6), so that constructor is preferred when available.
    """
    try:
        from . import exposure as _exposure
    except Exception as exc:
        return None, f"cannot build an exposure profile: moa_lib.exposure unavailable ({exc})"
    try:
        if modality == "herbal_formula" and route_source and \
                callable(getattr(_exposure, "herbal_formula_profile", None)):
            return (_exposure.herbal_formula_profile("", route, route_source,
                                                     formulation=formulation),
                    "profile built from the formula's own route source (formula-level)")
        builder = getattr(_exposure, "build_profile", None)
        if not callable(builder):
            return None, ("moa_lib.exposure exposes no build_profile(); pass `exposure_profile=` "
                          "or `reachability=` instead")
        return (builder(modality, route, formulation=formulation),
                "profile built from modality x route x formulation defaults")
    except Exception as exc:
        return None, (f"building an exposure profile for ({modality}, {route}, {formulation}) "
                      f"raised {type(exc).__name__}: {exc}")


def resolve_reachability(tissue: Optional[str], *, modality: str, route: str,
                         formulation: Optional[str] = None, profile: Any = None,
                         reachability: Any = None,
                         exposure_resolver: Optional[Callable] = None,
                         route_source: str = "",
                         dds_bridgeable: Optional[bool] = None,
                         dds_candidates: Iterable[str] = ()) -> ExposureCheck:
    """Can `route` deliver `modality` to the tissue of pathology?

    Precedence: an explicitly supplied `reachability` result > `exposure_resolver` >
    `moa_lib.exposure` (see EXPOSURE_INTERFACE). When none can answer, the result is
    `not_assessable` with a reason naming what is missing — never a silent pass.

    `dds_bridgeable` / `dds_candidates` come from the caller (route_feasibility /
    delivery_paths), because the exposure model does not itself know about delivery
    systems; they are merged onto whatever the resolver reported.
    """
    chk = ExposureCheck(tissue=tissue, route=normalize_route(route),
                        modality=normalize_modality(modality), formulation=formulation)

    def _finish(c: ExposureCheck) -> ExposureCheck:
        if dds_bridgeable is not None:
            c.dds_bridgeable = bool(dds_bridgeable) or c.dds_bridgeable
        extra = [str(d) for d in _as_list(dds_candidates) if d]
        c.dds_candidates = list(dict.fromkeys(c.dds_candidates + extra))
        if c.dds_candidates and dds_bridgeable is None and not c.dds_bridgeable:
            c.dds_bridgeable = True
        return c

    if not tissue:
        chk.level = "not_assessed"
        chk.reasons.append("tissue of pathology not supplied — route-vs-tissue exposure was NOT "
                           "assessed; supply `disease_tissue` (it is on the run card) to enable it")
        return _finish(chk)
    if chk.route == "unknown":
        chk.level = "not_assessable"
        chk.reasons.append("route of administration unknown — cannot judge whether the tissue of "
                           "pathology is reachable")
        return _finish(chk)

    if reachability is not None:
        chk.resolver = "caller-supplied reachability"
        return _finish(_normalise_reachability(reachability, chk))

    fn, info = (exposure_resolver, "caller-supplied exposure_resolver") if exposure_resolver \
        else _load_exposure_resolver()
    if fn is None:
        chk.level = "not_assessable"
        chk.reasons.append(info)
        return _finish(chk)
    chk.resolver = info

    # a resolver that needs an ExposureProfile gets one (see EXPOSURE_INTERFACE)
    if profile is None and _wants_param(fn, "profile"):
        profile, note = _build_profile(chk.modality, chk.route, formulation, route_source)
        chk.reasons.append(note)
        if profile is None:
            chk.level = "not_assessable"
            return _finish(chk)

    try:
        raw = _call_resolver(fn, tissue=tissue, modality=chk.modality, route=chk.route,
                             formulation=formulation, profile=profile)
    except Exception as exc:
        chk.level = "not_assessable"
        chk.reasons.append(f"exposure resolver {info} raised {type(exc).__name__}: {exc}")
        return _finish(chk)
    if raw is None:
        chk.level = "not_assessable"
        chk.reasons.append(f"exposure resolver {info} returned nothing for tissue '{tissue}'")
        return _finish(chk)
    return _finish(_normalise_reachability(raw, chk))


# --------------------------------------------------------------------------------------
# 6. Circularity control specification (consumed by Step 3)
# --------------------------------------------------------------------------------------
@dataclass
class CircularitySpec:
    triggered: bool
    compound: str = ""
    disease: str = ""
    reason: str = ""
    legs: list = field(default_factory=list)
    own_literature_pmids: list = field(default_factory=list)
    unclassifiable_pmids: list = field(default_factory=list)
    reporting: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"triggered": self.triggered, "compound": self.compound, "disease": self.disease,
                "reason": self.reason, "legs": self.legs,
                "own_literature_pmids": self.own_literature_pmids,
                "unclassifiable_pmids": self.unclassifiable_pmids, "reporting": self.reporting}


def is_own_compound_literature(record: Any, compound: str,
                               aliases: Iterable[str] = ()) -> tuple:
    """Is this stored publication 'the compound's own literature'? -> (bool, reasons)

    Definition used here (kernel design §8.4 left it to the builder):
      a record counts when BOTH hold —
        (a) it is ABOUT the compound: the compound name or one of its aliases (INN, brand,
            ChEMBL pref_name) appears in the title, the abstract, or the MeSH substance list;
        (b) it is one of CIRCULARITY_PUBTYPES — the trial family (the records a drug's own
            development programme generates) or the review/meta-analysis family (records that
            restate them). A record carrying an NCT id for the compound also counts, because
            PubMed publication-type indexing lags registration.
    Primary research on the TARGET rather than on the drug is deliberately NOT stripped:
    that is independent biology, and removing it would strip real evidence.

    `record` is a stored PubMed-shaped mapping:
        {"pmid": "...", "title": "...", "abstract": "...",
         "publication_types": [...], "mesh_substances": [...]}
    Returns (False, ["insufficient metadata ..."]) when types are absent — the caller must
    treat that as unclassifiable, not as clean.
    """
    names = [n for n in ([compound] + list(aliases or [])) if n]
    hay = " ".join(str(_get(record, k, default="") or "") for k in
                   ("title", "abstract", "journal")).lower()
    subs = [str(s).lower() for s in _as_list(_get(record, "mesh_substances", "substances",
                                                  "chemicals", default=[]))]
    about = [n for n in names if _norm(n) and (_norm(n) in hay or
                                               any(_norm(n) in s for s in subs))]
    pts = [_norm(p) for p in _as_list(_get(record, "publication_types", "pubtypes",
                                           "publication_type", default=[]))]
    hit_pt = [p for p in pts if p in CIRCULARITY_PUBTYPES]
    nct = CIRCULARITY_NCT_RE.findall(
        " ".join(str(_get(record, k, default="") or "") for k in
                 ("abstract", "title", "secondary_ids", "databank_accessions")))
    reasons = []
    if not about:
        return False, [f"not about the compound ({compound}) in title/abstract/MeSH substances"]
    reasons.append(f"about the compound (matched: {', '.join(about)})")
    if hit_pt:
        reasons.append(f"publication type(s): {', '.join(hit_pt)}")
        return True, reasons
    if nct:
        reasons.append(f"registers a trial of the compound ({', '.join(sorted(set(nct)))}) — "
                       f"counted as a trial although no trial publication type is indexed")
        return True, reasons
    if not pts:
        return False, reasons + ["publication types absent from the stored record — "
                                 "unclassifiable, fetch them before relying on this leg"]
    return False, reasons + [f"publication types {pts} are neither trial nor review — "
                             f"treated as independent literature and NOT stripped"]


def circularity_spec(compound: str, disease: str, indication_status: str, *,
                     publications: Optional[Iterable] = None,
                     compound_aliases: Iterable[str] = ()) -> CircularitySpec:
    """The specification Step 3 consumes to strip the drug's own evidence.

    Triggered when the compound is approved or trialled in the indication: its target's
    disease association is then partly its own trial evidence. The control strips BOTH
    legs and reports them SEPARATELY (kernel design §8.2 B2) — stripping only the Open
    Targets datatype leaves the drug's own trial papers carrying the gene through
    text-mining, which is how a circular target survived a recent run.
    """
    triggered = _norm(indication_status) in ("approved", "trialled")
    own, unclassifiable = [], []
    for rec in _as_list(publications):
        pmid = str(_get(rec, "pmid", "id", default="") or "")
        is_own, why = is_own_compound_literature(rec, compound, compound_aliases)
        if is_own:
            own.append({"pmid": pmid, "why": why})
        elif any("unclassifiable" in w for w in why):
            unclassifiable.append({"pmid": pmid, "why": why})

    legs = [
        {"leg": "i",
         "name": "open_targets_clinical_precedence",
         "strip": {"datatypeId": list(CIRCULARITY_OT_DATATYPES),
                   "datasourceId": list(CIRCULARITY_OT_DATASOURCES)},
         "how": "drop these evidence rows, then RECOMPUTE the List-B association score from "
                "the remaining datatypes (do not merely drop genes whose sole support is "
                "clinical precedence — that misses genes with mixed support)",
         "report_as": "listB_score_no_known_drug"},
        {"leg": "ii",
         "name": "compound_own_literature",
         "strip": {"pmids": [o["pmid"] for o in own if o["pmid"]],
                   "rule": {"about_compound": "name/alias in title, abstract or MeSH substances",
                            "publication_types": list(CIRCULARITY_PUBTYPES),
                            "also_counts": "a record registering an NCT id for the compound"}},
         "how": "drop these PMIDs from the literature/text-mining leg of List B, then recompute; "
                "report the gene-level delta separately from leg (i)",
         "report_as": "listB_score_no_own_literature"},
    ]
    reporting = {
        "type": "pre-registered secondary analysis (report-only)",
        "primary_unchanged": True,
        "rules": [
            "the primary analysis is unchanged; the circularity-controlled result is reported "
            "beside it and never silently replaces it",
            "where a hub survives the primary but not the control, the report must state that "
            "its disease association rests on the drug's own trial evidence",
            "each leg is reported separately, with its own gene-level delta",
            "confidence for any hub that depends on stripped evidence is capped at "
            "'promising-but-unproven'",
        ],
        "consumed_by": "Step 3 (specificity_controls) — pre-register in data/step3_prespec.json",
    }
    reason = ("" if not triggered else
              f"'{compound}' is {_norm(indication_status)} in '{disease}' — its target's disease "
              f"association is partly its own trial evidence")
    return CircularitySpec(triggered, compound, disease, reason, legs,
                           own_literature_pmids=own, unclassifiable_pmids=unclassifiable,
                           reporting=reporting)


# --------------------------------------------------------------------------------------
# 7. The gate
# --------------------------------------------------------------------------------------
@dataclass
class GateVerdict:
    # --- v11 field order preserved ---
    action: str
    composition: CompositionCheck
    route: str
    route_source: str
    indication: str                 # v11 vocabulary: established | novel/implausible | unknown
    indication_why: str
    reasons: list = field(default_factory=list)
    # --- v12 additions ---
    name: str = ""
    disease: str = ""
    modality: str = "unknown"
    formulation: Optional[str] = None
    exposure_route: str = "unknown"
    route_evidence_tier: str = ""
    indication_status: str = "unknown"      # approved|trialled|literature_supported|none|unknown
    indication_detail: Optional[IndicationResult] = None
    identity: Optional[IdentityCheck] = None
    exposure: Optional[ExposureCheck] = None
    circularity: Optional[CircularitySpec] = None
    labels: list = field(default_factory=list)
    required_inputs: list = field(default_factory=list)
    question: dict = field(default_factory=dict)
    caller_options: tuple = ()

    # convenience
    @property
    def halts(self) -> bool:
        return self.action in (HALT, EXPOSURE_MISMATCH)

    @property
    def halt_file(self) -> Optional[str]:
        return HALT_FILES.get(self.action)

    def as_dict(self) -> dict:
        """Flat, JSON-serialisable summary for `data/step0_data.json`."""
        return {
            "action": self.action, "name": self.name, "disease": self.disease,
            "modality": self.modality, "route": self.route,
            "exposure_route": self.exposure_route, "route_source": self.route_source,
            "route_evidence_tier": self.route_evidence_tier, "formulation": self.formulation,
            "composition_verdict": self.composition.verdict,
            "composition_variant": self.composition.matched_variant,
            "composition_variant_label": self.composition.matched_variant_label,
            "composition_source": self.composition.variant_source,
            "composition_source_kind": self.composition.variant_source_kind,
            "identity_verdict": getattr(self.identity, "verdict", None),
            "identity_matched_on": getattr(self.identity, "matched_on", []),
            "identity_missing": getattr(self.identity, "missing", []),
            "indication": self.indication, "indication_status": self.indication_status,
            "indication_why": self.indication_why,
            "exposure": {
                "assessed": getattr(self.exposure, "assessed", False),
                "tissue": getattr(self.exposure, "tissue", None),
                "level": getattr(self.exposure, "level", "not_assessed"),
                "reachable": getattr(self.exposure, "reachable", None),
                "compartments": getattr(self.exposure, "compartments", []),
                "target_compartment": getattr(self.exposure, "target_compartment", None),
                "via": getattr(self.exposure, "via", ""),
                "provisional": getattr(self.exposure, "provisional", False),
                "dds_bridgeable": getattr(self.exposure, "dds_bridgeable", False),
                "dds_candidates": getattr(self.exposure, "dds_candidates", []),
                "sources": getattr(self.exposure, "sources", []),
                "evidence_tier": getattr(self.exposure, "evidence_tier", ""),
            },
            "circularity": self.circularity.as_dict() if self.circularity else None,
            "labels": self.labels, "required_inputs": self.required_inputs,
            "reasons": self.reasons, "halt_file": self.halt_file,
        }


def _worst(a: str, b: str) -> str:
    return a if VERDICT_PRECEDENCE.index(a) <= VERDICT_PRECEDENCE.index(b) else b


def provenance_gate(name: str, provided_herbs: Optional[list] = None,
                    disease: Optional[str] = None, *,
                    modality: Optional[str] = None,
                    route: Optional[str] = None, route_source: Optional[str] = None,
                    formulation: Optional[str] = None,
                    composition_source: Optional[dict] = None,
                    identity_evidence: Optional[dict] = None,
                    indication_evidence: Optional[dict] = None,
                    disease_tissue: Optional[str] = None,
                    reachability: Any = None,
                    exposure_resolver: Optional[Callable] = None,
                    exposure_profile: Any = None,
                    dds_bridgeable: Optional[bool] = None,
                    dds_candidates: Iterable[str] = (),
                    publications: Optional[Iterable] = None,
                    compound_aliases: Iterable[str] = ()) -> GateVerdict:
    """Step-0 gate. Stops ONLY on a mis-specified object of study.

    Positional arguments keep the v11 signature `(name, provided_herbs, disease)`.

    Verdicts: PASS · REFRAME · HALT · EXPOSURE_MISMATCH · NEEDS_INPUT (see module docstring).
    The module never decides between asking the user and writing a HALT file: a
    NEEDS_INPUT verdict carries `required_inputs`, a ready `question` and
    `halt_report(verdict)` so the caller can do either.
    """
    herbs = list(provided_herbs or [])
    mod = normalize_modality(modality)
    if mod == "unknown":
        mod = "herbal_formula" if (herbs or _lookup(name)) else "unknown"

    # --- composition (herbal only) -----------------------------------------------------
    if mod == "herbal_formula":
        comp = validate_composition(name, herbs, composition_source=composition_source)
    else:
        comp = CompositionCheck(False, len(herbs), None, verdict="not_applicable",
                                reasons=[f"modality '{mod}' — composition check not applicable; "
                                         f"identity is verified from "
                                         f"{', '.join(IDENTITY_REQUIREMENTS.get(mod, ('supplied evidence',)))}"])

    # --- identity ----------------------------------------------------------------------
    ident = verify_identity(mod, name, identity_evidence, provided_herbs=herbs,
                            composition_source=composition_source)

    # --- route (for the exposure model) ------------------------------------------------
    rinfo = classify_route(name, route=route, route_source=route_source, formulation=formulation)

    # --- indication --------------------------------------------------------------------
    ind = indication_plausibility(name, disease or "", evidence=indication_evidence)

    # --- exposure ----------------------------------------------------------------------
    exp = resolve_reachability(disease_tissue, modality=mod, route=rinfo.route,
                               formulation=formulation, profile=exposure_profile,
                               reachability=reachability, exposure_resolver=exposure_resolver,
                               route_source=rinfo.source, dds_bridgeable=dds_bridgeable,
                               dds_candidates=dds_candidates)

    # --- circularity -------------------------------------------------------------------
    circ = circularity_spec(name, disease or "", ind.status, publications=publications,
                            compound_aliases=compound_aliases)

    # --- fold into one action ----------------------------------------------------------
    action, reasons, labels, needed = PASS, [], [], []

    if comp.verdict == "mismatch":
        action = _worst(action, HALT)
        reasons.append("composition mismatch — analysing the wrong preparation: "
                       + "; ".join(comp.reasons))
    elif comp.verdict == "unsourceable":
        action = _worst(action, HALT)
        reasons.append("composition cannot be sourced: " + "; ".join(comp.reasons))
    elif comp.verdict == "unknown":
        action = _worst(action, NEEDS_INPUT)
        reasons.append("formula/composition unverified: " + "; ".join(comp.reasons))
        needed.append("the composition source for '%s' — the classical/pharmacopoeia text or "
                      "publication it comes from, or an explicit statement that it is the lab's "
                      "own preparation" % name)
    elif comp.verdict == "user_provided_variant":
        labels.append("user_provided_composition")
        reasons.append("composition recorded as the user's/lab's own preparation "
                       f"(source: {comp.variant_source}) — the report must state that it is not "
                       f"a classical composition")
    elif comp.verdict == "match":
        reasons.append(f"composition matches sourced variant '{comp.matched_variant}' "
                       f"({comp.variant_source})")
    elif comp.verdict == "sourced_external":
        labels.append("composition_not_in_reference_table")
        reasons.append("; ".join(comp.reasons))

    if mod != "herbal_formula":
        if ident.halts:
            action = _worst(action, HALT)
            reasons.append(f"identity not verified ({ident.verdict}): "
                           + "; ".join(ident.conflicts or ident.missing))
        elif ident.needs_input:
            action = _worst(action, NEEDS_INPUT)
            reasons.append(f"identity verification incomplete for modality '{mod}'")
            needed.extend(ident.missing)
        else:
            reasons.append("identity verified: " + "; ".join(ident.matched_on))
    if ident.notes:
        reasons.extend(ident.notes)

    if rinfo.route == "unknown":
        reasons.append("route of administration unknown — it is a first-class run variable "
                       "(it sets the exposure profile); supply it from the label or the "
                       "formula's source")
        if disease_tissue:
            action = _worst(action, NEEDS_INPUT)
            needed.append("route of administration (from the label / the formula's source)")
    else:
        reasons.append(f"route: {rinfo.route} (exposure route '{rinfo.exposure_route}', "
                       f"{rinfo.evidence_tier or 'unsourced'}) — {rinfo.source}")

    if exp.mismatch:
        action = _worst(action, EXPOSURE_MISMATCH)
        reasons.append(f"route '{rinfo.route}' (compartments: "
                       f"{', '.join(exp.compartments) or 'unstated'}) cannot reach the tissue of "
                       f"pathology '{exp.tissue}' — a systemic/efficacy claim here would be a "
                       f"category error")
        if exp.dds_bridgeable:
            labels.append("development_path")
            reasons.append("a delivery system could plausibly bridge the gap"
                           + (f" (candidates: {', '.join(exp.dds_candidates)})"
                              if exp.dds_candidates else "")
                           + " — route to the development path rather than claiming efficacy by "
                             "this route")
    elif exp.level == "dds_enabled":
        labels.append("delivery_dependent")
        reasons.append(f"tissue '{exp.tissue}' is reachable only with an enabling delivery system"
                       + (f" ({', '.join(exp.dds_candidates)})" if exp.dds_candidates else "")
                       + " — mechanisms anchored here are delivery-dependent")
    elif exp.level == "not_assessable" and disease_tissue:
        action = _worst(action, NEEDS_INPUT)
        needed.append(f"exposure reachability for tissue '{disease_tissue}' "
                      f"(moa_lib.exposure, or pass `reachability=`/`exposure_resolver=`)")
    reasons.extend(exp.reasons)
    if exp.assessed and exp.provisional:
        labels.append("provisional_exposure_profile")
        reasons.append("exposure profile rests on a rule of thumb (E4) — provisional; it cannot "
                       "alone support a systemic or responder claim")

    if ind.status == "none":
        action = _worst(action, REFRAME)
        labels.append("traditional_use_only" if ind.traditional_use else "repurposing_hypothesis")
        reasons.append(f"indication: {ind.why}")
    elif ind.status == "unknown":
        action = _worst(action, REFRAME)
        labels.append("repurposing_hypothesis")
        reasons.append(f"indication: {ind.why}")
    else:
        reasons.append(f"indication ({ind.status}, {ind.evidence_tier}): {ind.why}")
    if ind.user_claims:
        labels.append("user_provided_efficacy_claim")
    if circ.triggered:
        labels.append("circularity_control_required")
        reasons.append(circ.reason + " — run the pre-registered Step-3 circularity control "
                                     "(both legs, reported separately)")

    question = {}
    if action == NEEDS_INPUT:
        question = {
            "headline": f"Step 0 cannot verify the object of study for '{name}'"
                        + (f" in '{disease}'" if disease else ""),
            "needs": needed,
            "why": "proceeding without it would analyse an object of study that may not be the "
                   "one you mean — the failure this gate exists to prevent",
        }

    verdict = GateVerdict(
        action=action, composition=comp, route=rinfo.route, route_source=rinfo.source,
        indication=ind.legacy_status, indication_why=ind.why, reasons=reasons,
        name=name, disease=disease or "", modality=mod, formulation=formulation,
        exposure_route=rinfo.exposure_route, route_evidence_tier=rinfo.evidence_tier,
        indication_status=ind.status, indication_detail=ind, identity=ident, exposure=exp,
        circularity=circ, labels=labels, required_inputs=needed, question=question,
        caller_options=(("ask_user", "write_halt_file") if action == NEEDS_INPUT
                        else (("write_halt_file",) if action in (HALT, EXPOSURE_MISMATCH) else ())),
    )
    return verdict


# --------------------------------------------------------------------------------------
# 8. Stop-report rendering (the caller writes the file; the module supplies the body)
# --------------------------------------------------------------------------------------
def halt_filename(verdict: GateVerdict) -> Optional[str]:
    return HALT_FILES.get(verdict.action)


def halt_report(verdict: GateVerdict) -> str:
    """Markdown body for `HALT_provenance.md` / `HALT_exposure_mismatch.md`."""
    v = verdict
    title = {HALT: "Step 0 halt — mis-specified object of study",
             EXPOSURE_MISMATCH: "Step 0 halt — route cannot reach the tissue of pathology",
             NEEDS_INPUT: "Step 0 cannot proceed — missing information"}.get(
                 v.action, "Step 0 outcome")
    lines = [f"# {title}", "",
             f"**Object of study:** {v.name}" + (f"  ·  **Condition:** {v.disease}" if v.disease else ""),
             f"**Modality:** {v.modality}  ·  **Route:** {v.route}"
             + (f" ({v.exposure_route})" if v.exposure_route != v.route else "")
             + (f"  ·  **Formulation:** {v.formulation}" if v.formulation else ""),
             f"**Verdict:** {v.action}", ""]
    if v.action == EXPOSURE_MISMATCH and v.exposure:
        lines += ["## Route vs tissue of pathology", "",
                  f"- Tissue of pathology: **{v.exposure.tissue}**",
                  f"- Compartments this route reaches: "
                  f"{', '.join(v.exposure.compartments) or 'not stated by the exposure model'}",
                  f"- Source(s): {'; '.join(v.exposure.sources) or 'not stated'}"
                  + (f" (evidence tier {v.exposure.evidence_tier})" if v.exposure.evidence_tier else ""),
                  f"- A delivery system could bridge the gap: "
                  f"**{'yes' if v.exposure.dds_bridgeable else 'no'}**"
                  + (f" — candidate classes: {', '.join(v.exposure.dds_candidates)}"
                     if v.exposure.dds_candidates else ""), ""]
        if v.exposure.dds_bridgeable:
            lines += ["This run stops as a *delivery* question, not an efficacy question: the "
                      "mechanism may be real but is not reachable by this route as formulated. "
                      "Route it to the development path (barrier → DDS class → precedent → "
                      "decisive delivery experiment) instead of claiming efficacy by this route.", ""]
    if v.required_inputs:
        lines += ["## What is needed", ""] + [f"- {r}" for r in v.required_inputs] + [""]
    lines += ["## Findings", ""] + [f"- {r}" for r in v.reasons] + [""]
    if v.composition and v.composition.candidate_variants:
        lines += ["## Composition vs sourced variants", "",
                  "| variant | source | herbs | missing | extra |", "|---|---|---|---|---|"]
        for d in v.composition.candidate_variants:
            lines.append(f"| {d['variant_id']} | {d.get('source', '')} | {d['herb_count']} | "
                         f"{', '.join(d['missing']) or '-'} | "
                         f"{', '.join(str(e) for e in d['extra']) or '-'} |")
        lines.append("")
    if v.labels:
        lines += ["## Labels", "", ", ".join(sorted(set(v.labels))), ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# References for the rules encoded above (run them through citation_grounding when cited)
# --------------------------------------------------------------------------------------
REFERENCES = {
    "MISEV2018": {
        "citation": "Théry, C., et al. (2018). Minimal information for studies of extracellular "
                    "vesicles 2018 (MISEV2018). Journal of Extracellular Vesicles, 7(1), 1535750.",
        "doi": "10.1080/20013078.2018.1535750",
        "used_for": "EV identity: positive/negative marker and single-particle requirements",
    },
    "MISEV2023": {
        "citation": "Welsh, J. A., et al. (2024). Minimal information for studies of extracellular "
                    "vesicles (MISEV2023). Journal of Extracellular Vesicles, 13(2), e12404.",
        "doi": "10.1002/jev2.12404",
        "used_for": "EV identity: current minimum-information items and reporting expectations",
    },
    "Nelson2015": {
        "citation": "Nelson, M. R., et al. (2015). The support of human genetic evidence for "
                    "approved drug indications. Nature Genetics, 47(8), 856-860.",
        "doi": "10.1038/ng.3314",
        "used_for": "why genetic evidence is prioritised over clinical-precedence evidence, "
                    "which the circularity control strips",
    },
}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    s9 = ["白朮 Atractylodes", "白芷 Angelica dahurica", "白及 Bletilla striata",
          "白蘞 Ampelopsis japonica", "白茯苓 Poria cocos"]
    g = provenance_gate("Qibai San (七白散)", s9, "Atopic Dermatitis", modality="herbal_formula")
    print("Session-9 list   ->", g.action, "|", g.composition.verdict)
    authentic = ["白蘞", "白朮", "白牽牛", "白芍藥", "白僵蠶", "白芷", "白附子"]
    g2 = provenance_gate("七白散", authentic, "Atopic Dermatitis", modality="herbal_formula")
    print("authentic 7-herb ->", g2.action, "| variant:", g2.composition.matched_variant,
          "| route:", g2.route, "->", g2.exposure_route)
