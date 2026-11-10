"""Exposure model (v12) — where a drug actually goes, and on whose authority.

Design: `docs/superpowers/specs/2026-11-10-moa-kernel-design.md` §4.4, §8.2 B3/B6.

The v11 pipeline knew one exposure question ("is this topical?") and answered it
from a formula table. Every other modality and route either got a meaningless
Lipinski verdict or none at all. This module replaces that with an explicit,
**sourced** exposure profile built from three independent inputs:

    modality  x  route  x  formulation       ->  ExposureProfile

Route and formulation are independent: within one route the formulation changes
exposure (a plain SC injection vs a depot; a cream vs a microneedle array).

    build_profile(modality, route, formulation=None, observations=(), compound="")
    herbal_formula_profile(formula, route, source, ...)        # B6: formula-level E1
    constituent_profile(formula_profile, constituent, ...)     # B6: provisional systemic
    reaches_target_tissue(profile, tissue)                     # B3: reachability
    exposure_mismatch(profile, tissue)                         # B3: Step-0 EXPOSURE_MISMATCH

Nothing here predicts a PK number. The profile is **categorical and sourced**
(design §3, non-goals): `primary_compartments`, `systemic` and `cns`, each field
carrying the source it came from and that source's evidence tier.

Source priority (design §4.4), highest first:

    1. label            the approved label's route + clinical-pharmacology section   E0
    2. chembl_flag      ChEMBL molecule flags (oral / parenteral / topical)          E2
    3. published_pk     measured PK in a grounded publication                        E1
    4. classical_source a classical / pharmacopoeia route for a herbal formula       E1
    5. rule_of_thumb    this module's route default                                  E4

Priority is not the same as tier, and the inversion at 2 vs 3 is deliberate: a
ChEMBL route flag describes how *this exact molecule* is actually marketed, while
a published PK study may be in another species, salt or formulation. The tier
still records how strong the evidence is, and `tier_of(field)` reports it.

**A rule-of-thumb default is E4** (design §8.2 B6). It is recorded, never hidden,
and it cannot by itself support a systemic or a responder claim: such a profile is
`provisional`, and `supports_systemic_claim()` / `supports_responder_claim()`
return False with the reason. For a herbal formula the formula-level route from a
classical or pharmacopoeia source is a legitimate **E1** source for the
*compartment* and applies to the constituents; a constituent's **systemic**
exposure stays provisional until that constituent has its own PK.

Compartment vocabulary
----------------------
Flat tokens, deliberately at the granularity a delivery decision needs — the
compartment a drug is placed in or reaches, not an anatomy ontology. Three facts
are attached to each token and that is what reachability reasons over:

  * **luminal / outside-the-barrier** compartments are reached only by applying the
    drug there (`skin_surface`, `skin_stratum_corneum`, `gut_lumen`, `airway_lumen`,
    `ocular_surface`, `ear_external`, and the mucosal surfaces). Systemic exposure
    does *not* reach them, which is why an oral drug does not treat the skin surface
    and an IV drug does not coat the airway.
  * **perfused** compartments are reached from plasma once there is systemic
    exposure (`liver`, `kidney`, `bone_marrow`, `lymphoid_tissue`, `skin_dermis`,
    `lung_parenchyma`, `gut_mucosa`, `muscle_local`, `subcutis`, `synovium`,
    `other_perfused_tissue`, and `plasma` itself).
  * **barrier-restricted** compartments need their own evidence even when systemic
    exposure is full: `cns` and `csf` (blood-brain barrier, governed by the `cns`
    field) and `eye_anterior` / `eye_posterior` (blood-ocular barriers).

Why this shape rather than an ontology (design §7 left the vocabulary to the
builder): the only question the kernel asks is "does this route put the molecule
where the pathology is", and that question needs a barrier model, not a taxonomy.
A UBERON id would not say whether plasma reaches a compartment. Tissue free text
("lesional skin", "bone marrow", "liver") is mapped onto these tokens by
`resolve_compartment()`, and an unmapped tissue returns `not_assessable` rather
than a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

from .evidence_schema import Tier

# --------------------------------------------------------------------------- #
# vocabularies
# --------------------------------------------------------------------------- #


class Modality(str, Enum):
    SMALL_MOLECULE = "small_molecule"
    PEPTIDE = "peptide"
    PROTEIN_ANTIBODY = "protein_antibody"
    OLIGONUCLEOTIDE = "oligonucleotide"
    HERBAL_FORMULA = "herbal_formula"
    EXTRACELLULAR_VESICLE = "extracellular_vesicle"
    CELL = "cell"
    OTHER = "other"


class Route(str, Enum):
    ORAL = "oral"
    TOPICAL_SKIN = "topical_skin"
    TRANSDERMAL = "transdermal"
    SUBCUTANEOUS = "subcutaneous"
    INTRAMUSCULAR = "intramuscular"
    INTRAVENOUS = "intravenous"
    INHALED = "inhaled"
    INTRANASAL = "intranasal"
    OPHTHALMIC = "ophthalmic"
    OTIC = "otic"
    BUCCAL_SUBLINGUAL = "buccal_sublingual"
    RECTAL = "rectal"
    VAGINAL = "vaginal"
    INTRA_ARTICULAR = "intra_articular"
    INTRATHECAL = "intrathecal"
    OTHER = "other"


#: Routes that place the drug inside the body, so absorption rules do not apply.
PARENTERAL_ROUTES = frozenset({
    Route.SUBCUTANEOUS, Route.INTRAMUSCULAR, Route.INTRAVENOUS,
    Route.INTRA_ARTICULAR, Route.INTRATHECAL,
})

#: Controlled formulation vocabulary. Free text is allowed (design §4.4): an
#: unrecognised string is kept verbatim and flagged as uncontrolled, never dropped.
FORMULATION_VOCAB = frozenset({
    "tablet", "capsule", "delayed_release_capsule", "solution", "suspension",
    "syrup", "powder", "decoction", "granule", "pill",
    "cream", "ointment", "gel", "lotion", "foam", "paste", "mask",
    "patch", "nanoemulsion", "microemulsion", "liposome", "ethosome", "niosome",
    "lnp", "polymeric_nanoparticle", "micelle", "microneedle", "hydrogel",
    "depot", "implant", "prefilled_syringe", "autoinjector", "lyophilisate",
    "dpi", "mdi", "nebulised", "nasal_spray",
    "eye_drop", "eye_ointment", "intravitreal_implant", "ear_drop",
    "suppository", "pessary", "enema",
})

# --- compartments ---------------------------------------------------------- #

#: Reached only by applying the drug there; systemic exposure does NOT reach them.
LUMINAL_COMPARTMENTS = frozenset({
    "skin_surface", "skin_stratum_corneum", "gut_lumen", "airway_lumen",
    "ocular_surface", "ear_external", "nasal_mucosa", "oral_mucosa",
    "rectal_mucosa", "vaginal_mucosa",
})

#: Reached from plasma whenever there is systemic exposure.
PERFUSED_COMPARTMENTS = frozenset({
    "plasma", "liver", "kidney", "bone_marrow", "lymphoid_tissue",
    "lung_parenchyma", "gut_mucosa", "muscle_local", "subcutis", "synovium",
    "skin_dermis", "skin_epidermis", "skin_appendage", "other_perfused_tissue",
})

#: Need their own evidence even when systemic exposure is full.
BARRIER_RESTRICTED_COMPARTMENTS = frozenset({
    "cns", "csf", "eye_anterior", "eye_posterior",
})

COMPARTMENTS = LUMINAL_COMPARTMENTS | PERFUSED_COMPARTMENTS | BARRIER_RESTRICTED_COMPARTMENTS

#: Tissue free text -> compartment token. Longest match wins (see
#: `resolve_compartment`); an unmapped tissue is `not_assessable`, never guessed.
_TISSUE_SYNONYMS = {
    "stratum corneum": "skin_stratum_corneum",
    "skin surface": "skin_surface",
    "epidermis": "skin_epidermis",
    "lesional skin": "skin_epidermis",
    "lesional epidermis": "skin_epidermis",
    "keratinocyte": "skin_epidermis",
    "atopic dermatitis skin": "skin_epidermis",
    "dermis": "skin_dermis",
    "hair follicle": "skin_appendage",
    "sebaceous gland": "skin_appendage",
    "sweat gland": "skin_appendage",
    "skin": "skin_epidermis",
    "blood": "plasma",
    "plasma": "plasma",
    "serum": "plasma",
    "circulation": "plasma",
    "systemic circulation": "plasma",
    "liver": "liver",
    "hepatocyte": "liver",
    "hepatic": "liver",
    "kidney": "kidney",
    "renal": "kidney",
    "bone marrow": "bone_marrow",
    "marrow": "bone_marrow",
    "haematopoietic": "bone_marrow",
    "hematopoietic": "bone_marrow",
    "myelofibrosis": "bone_marrow",
    "lymph node": "lymphoid_tissue",
    "spleen": "lymphoid_tissue",
    "lymphoid": "lymphoid_tissue",
    "lung": "lung_parenchyma",
    "alveolar": "lung_parenchyma",
    "lung parenchyma": "lung_parenchyma",
    "airway": "airway_lumen",
    "bronchial": "airway_lumen",
    "bronchus": "airway_lumen",
    "nasal mucosa": "nasal_mucosa",
    "nose": "nasal_mucosa",
    "gut lumen": "gut_lumen",
    "intestinal lumen": "gut_lumen",
    "colonic lumen": "gut_lumen",
    "gut microbiome": "gut_lumen",
    "gut mucosa": "gut_mucosa",
    "intestinal mucosa": "gut_mucosa",
    "colon": "gut_mucosa",
    "intestine": "gut_mucosa",
    "gut": "gut_mucosa",
    "muscle": "muscle_local",
    "skeletal muscle": "muscle_local",
    "subcutis": "subcutis",
    "subcutaneous tissue": "subcutis",
    "adipose": "subcutis",
    "joint": "synovium",
    "synovium": "synovium",
    "synovial": "synovium",
    "cartilage": "synovium",
    "cornea": "eye_anterior",
    "aqueous humour": "eye_anterior",
    "aqueous humor": "eye_anterior",
    "anterior chamber": "eye_anterior",
    "ciliary body": "eye_anterior",
    "trabecular meshwork": "eye_anterior",
    "iris": "eye_anterior",
    "ocular surface": "ocular_surface",
    "conjunctiva": "ocular_surface",
    "tear film": "ocular_surface",
    "retina": "eye_posterior",
    "vitreous": "eye_posterior",
    "choroid": "eye_posterior",
    "brain": "cns",
    "cns": "cns",
    "central nervous system": "cns",
    "hypothalamus": "cns",
    "neuron": "cns",
    "cerebrospinal fluid": "csf",
    "csf": "csf",
    "intrathecal space": "csf",
    "external ear": "ear_external",
    "ear canal": "ear_external",
    "oral mucosa": "oral_mucosa",
    "buccal mucosa": "oral_mucosa",
    "rectal mucosa": "rectal_mucosa",
    "rectum": "rectal_mucosa",
    "vagina": "vaginal_mucosa",
    "vaginal mucosa": "vaginal_mucosa",
}

#: Rule-of-thumb route defaults. **Tier E4** (design §8.2 B6): recorded, flagged,
#: and unable on their own to support a systemic or responder claim. They state
#: only what the route means anatomically; nothing here is molecule-specific.
ROUTE_DEFAULTS = {
    Route.ORAL: (["gut_lumen", "gut_mucosa", "liver", "plasma"], "full", "possible"),
    Route.TOPICAL_SKIN: (["skin_surface", "skin_stratum_corneum", "skin_epidermis",
                          "skin_dermis", "skin_appendage"], "low", "unlikely"),
    Route.TRANSDERMAL: (["skin_stratum_corneum", "skin_epidermis", "skin_dermis",
                         "plasma"], "full", "possible"),
    Route.SUBCUTANEOUS: (["subcutis", "plasma"], "full", "unlikely"),
    Route.INTRAMUSCULAR: (["muscle_local", "plasma"], "full", "unlikely"),
    Route.INTRAVENOUS: (["plasma"], "full", "unlikely"),
    Route.INHALED: (["airway_lumen", "lung_parenchyma", "plasma"], "low", "unlikely"),
    Route.INTRANASAL: (["nasal_mucosa", "plasma"], "low", "unlikely"),
    Route.OPHTHALMIC: (["ocular_surface", "eye_anterior"], "low", "unlikely"),
    Route.OTIC: (["ear_external"], "none", "unlikely"),
    Route.BUCCAL_SUBLINGUAL: (["oral_mucosa", "plasma"], "full", "possible"),
    Route.RECTAL: (["rectal_mucosa", "plasma"], "full", "possible"),
    Route.VAGINAL: (["vaginal_mucosa", "plasma"], "low", "unlikely"),
    Route.INTRA_ARTICULAR: (["synovium", "plasma"], "low", "unlikely"),
    Route.INTRATHECAL: (["csf", "cns", "plasma"], "low", "yes"),
    Route.OTHER: ([], "unknown", "unlikely"),
}

#: Modality adjustments to the E4 route default, applied after ROUTE_DEFAULTS.
#: Macromolecules given by mouth are degraded in the gut and are not systemically
#: available without an enabling delivery system (see `route_feasibility`'s
#: precedent-required rule sets). Still E4 — a rule of thumb, flagged as one.
_MACROMOLECULES = frozenset({Modality.PEPTIDE, Modality.PROTEIN_ANTIBODY,
                             Modality.OLIGONUCLEOTIDE, Modality.EXTRACELLULAR_VESICLE,
                             Modality.CELL})

SYSTEMIC_LEVELS = ("none", "low", "full", "unknown")
CNS_LEVELS = ("unlikely", "possible", "yes")

# source kinds, in priority order (design §4.4)
SOURCE_KINDS = ("label", "chembl_flag", "published_pk", "classical_source", "rule_of_thumb")
_SOURCE_PRIORITY = {k: i for i, k in enumerate(SOURCE_KINDS)}
_SOURCE_TIER = {
    "label": Tier.E0,
    "chembl_flag": Tier.E2,
    "published_pk": Tier.E1,
    "classical_source": Tier.E1,
    "rule_of_thumb": Tier.E4,
}

PROFILE_FIELDS = ("primary_compartments", "systemic", "cns")

# reachability verdicts
REACHABLE_DIRECT = "reachable_direct"
REACHABLE_SYSTEMIC = "reachable_systemic"
NOT_DELIVERABLE_TO_TARGET_TISSUE = "not_deliverable_to_target_tissue"
NOT_ASSESSABLE = "not_assessable"


# --------------------------------------------------------------------------- #
# normalisation helpers
# --------------------------------------------------------------------------- #

_ROUTE_ALIASES = {
    "topical": Route.TOPICAL_SKIN, "external": Route.TOPICAL_SKIN,
    "cutaneous": Route.TOPICAL_SKIN, "dermal": Route.TOPICAL_SKIN,
    "skin": Route.TOPICAL_SKIN, "外用": Route.TOPICAL_SKIN,
    "po": Route.ORAL, "per os": Route.ORAL, "by mouth": Route.ORAL,
    "内服": Route.ORAL, "內服": Route.ORAL, "口服": Route.ORAL,
    "sc": Route.SUBCUTANEOUS, "subcut": Route.SUBCUTANEOUS,
    "im": Route.INTRAMUSCULAR, "iv": Route.INTRAVENOUS, "intravenously": Route.INTRAVENOUS,
    "inhalation": Route.INHALED, "pulmonary": Route.INHALED,
    "nasal": Route.INTRANASAL, "intranasally": Route.INTRANASAL,
    "ocular": Route.OPHTHALMIC, "eye": Route.OPHTHALMIC, "eye drop": Route.OPHTHALMIC,
    "sublingual": Route.BUCCAL_SUBLINGUAL, "buccal": Route.BUCCAL_SUBLINGUAL,
    "it": Route.INTRATHECAL, "ia": Route.INTRA_ARTICULAR,
    "unknown": Route.OTHER, "": Route.OTHER,
}

_MODALITY_ALIASES = {
    "small molecule": Modality.SMALL_MOLECULE, "smallmolecule": Modality.SMALL_MOLECULE,
    "nce": Modality.SMALL_MOLECULE, "chemical": Modality.SMALL_MOLECULE,
    "antibody": Modality.PROTEIN_ANTIBODY, "mab": Modality.PROTEIN_ANTIBODY,
    "protein": Modality.PROTEIN_ANTIBODY, "biologic": Modality.PROTEIN_ANTIBODY,
    "sirna": Modality.OLIGONUCLEOTIDE, "aso": Modality.OLIGONUCLEOTIDE,
    "oligo": Modality.OLIGONUCLEOTIDE, "mrna": Modality.OLIGONUCLEOTIDE,
    "herbal": Modality.HERBAL_FORMULA, "tcm": Modality.HERBAL_FORMULA,
    "formula": Modality.HERBAL_FORMULA, "decoction": Modality.HERBAL_FORMULA,
    "exosome": Modality.EXTRACELLULAR_VESICLE, "ev": Modality.EXTRACELLULAR_VESICLE,
    "cell therapy": Modality.CELL, "car-t": Modality.CELL, "car t": Modality.CELL,
    "unknown": Modality.OTHER, "": Modality.OTHER,
}


def _norm(s) -> str:
    return (str(s) if s is not None else "").strip().lower()


def normalize_route(route) -> Route:
    """Map a route string (incl. v11 'topical'/'oral' and common abbreviations)
    onto the Route vocabulary. Unrecognised -> Route.OTHER (never a guess)."""
    if isinstance(route, Route):
        return route
    r = _norm(route).replace("-", "_")
    try:
        return Route(r)
    except ValueError:
        pass
    return _ROUTE_ALIASES.get(r, _ROUTE_ALIASES.get(r.replace("_", " "), Route.OTHER))


def normalize_modality(modality) -> Modality:
    if isinstance(modality, Modality):
        return modality
    m = _norm(modality).replace("-", "_")
    try:
        return Modality(m)
    except ValueError:
        pass
    return _MODALITY_ALIASES.get(m, _MODALITY_ALIASES.get(m.replace("_", " "), Modality.OTHER))


def normalize_formulation(formulation) -> tuple:
    """-> (value, in_controlled_vocabulary). Free text is kept verbatim (design §4.4)."""
    if formulation is None:
        return (None, True)
    f = _norm(formulation).replace(" ", "_").replace("-", "_")
    if f in FORMULATION_VOCAB:
        return (f, True)
    return (str(formulation).strip(), False)


def resolve_compartment(tissue) -> Optional[str]:
    """Map tissue free text onto a compartment token. Longest synonym wins, and a
    synonym matches only at word boundaries (a trailing plural is allowed) — a bare
    substring match would read "foreskin" as skin and "years of symptoms" as ear.

    Returns None when the tissue cannot be mapped. The caller must then report
    `not_assessable` rather than assume reachability.
    """
    if tissue is None:
        return None
    t = _norm(tissue)
    if not t:
        return None
    if t in COMPARTMENTS:
        return t
    if t in _TISSUE_SYNONYMS:
        return _TISSUE_SYNONYMS[t]
    best = None
    for syn, comp in _TISSUE_SYNONYMS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(syn)}(?:s|es)?(?![a-z0-9])", t) and \
                (best is None or len(syn) > len(best[0])):
            best = (syn, comp)
    return best[1] if best else None


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FieldSource:
    """Where one profile field came from, and how strong that is.

    `citation` must be a resolvable identifier (DailyMed setid, FDA application
    number, PMID:/DOI, ChEMBL id, or a named classical/pharmacopoeia text). A
    rule-of-thumb source carries no citation by definition and is tier E4.
    """
    kind: str                       # one of SOURCE_KINDS
    citation: str = ""
    detail: str = ""

    def __post_init__(self):
        if self.kind not in _SOURCE_PRIORITY:
            raise ValueError(f"unknown source kind {self.kind!r}; expected one of {SOURCE_KINDS}")

    @property
    def tier(self) -> Tier:
        return _SOURCE_TIER[self.kind]

    @property
    def priority(self) -> int:
        return _SOURCE_PRIORITY[self.kind]

    @property
    def is_rule_of_thumb(self) -> bool:
        return self.kind == "rule_of_thumb"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "citation": self.citation, "detail": self.detail,
                "tier": self.tier.value}


def label_source(citation: str, detail: str = "") -> FieldSource:
    return FieldSource("label", citation, detail)


def chembl_flag_source(citation: str, detail: str = "") -> FieldSource:
    return FieldSource("chembl_flag", citation, detail)


def published_pk_source(citation: str, detail: str = "") -> FieldSource:
    return FieldSource("published_pk", citation, detail)


def classical_source(citation: str, detail: str = "") -> FieldSource:
    return FieldSource("classical_source", citation, detail)


def rule_of_thumb_source(detail: str = "") -> FieldSource:
    return FieldSource("rule_of_thumb", "", detail)


@dataclass(frozen=True)
class Observation:
    """One sourced statement about one profile field."""
    field: str                      # one of PROFILE_FIELDS
    value: object
    source: FieldSource

    def __post_init__(self):
        if self.field not in PROFILE_FIELDS:
            raise ValueError(f"unknown profile field {self.field!r}; expected {PROFILE_FIELDS}")
        if self.field == "systemic" and self.value not in SYSTEMIC_LEVELS:
            raise ValueError(f"systemic must be one of {SYSTEMIC_LEVELS}, got {self.value!r}")
        if self.field == "cns" and self.value not in CNS_LEVELS:
            raise ValueError(f"cns must be one of {CNS_LEVELS}, got {self.value!r}")
        if self.field == "primary_compartments":
            unknown = [c for c in (self.value or []) if c not in COMPARTMENTS]
            if unknown:
                raise ValueError(f"unknown compartment(s) {unknown}; vocabulary: "
                                 f"{sorted(COMPARTMENTS)}")


# --------------------------------------------------------------------------- #
# the profile
# --------------------------------------------------------------------------- #


@dataclass
class ExposureProfile:
    modality: str
    route: str
    formulation: Optional[str]
    primary_compartments: list
    systemic: str                           # none | low | full | unknown
    cns: str                                # unlikely | possible | yes
    field_sources: dict = field(default_factory=dict)   # field -> FieldSource
    compound: str = ""
    formulation_in_vocab: bool = True
    notes: list = field(default_factory=list)

    # ---- provenance ------------------------------------------------------- #
    def source_of(self, fld: str) -> Optional[FieldSource]:
        return self.field_sources.get(fld)

    def tier_of(self, fld: str) -> Tier:
        src = self.field_sources.get(fld)
        return src.tier if src else Tier.E4

    @property
    def provisional_fields(self) -> list:
        """Fields resting only on a rule-of-thumb default (E4)."""
        return [f for f in PROFILE_FIELDS
                if f in self.field_sources and self.field_sources[f].is_rule_of_thumb]

    @property
    def provisional(self) -> bool:
        """True when any determinative field rests only on a rule of thumb (B6)."""
        return bool(self.provisional_fields)

    # ---- claim gates (CLAUDE.md §5 exposure-gated framing; design §8.2 B6) -- #
    def supports_systemic_claim(self) -> tuple:
        """May this profile carry a systemic-activity claim? -> (bool, reason).

        Requires `systemic == 'full'` from a source better than a rule of thumb.
        A 'low' profile supports statements *about* minimal systemic exposure
        (e.g. a topical label's clinical pharmacology), not systemic efficacy.
        """
        src = self.field_sources.get("systemic")
        if self.systemic == "unknown" or src is None:
            return (False, "systemic exposure not determined — no sourced value")
        if src.is_rule_of_thumb:
            return (False, f"systemic exposure rests only on a rule-of-thumb default "
                           f"({src.tier.value}); provisional — a label, ChEMBL route flag or "
                           f"published PK is required before any systemic claim")
        if self.systemic == "none":
            return (False, f"route {self.route} gives no systemic exposure "
                           f"({src.kind}: {src.citation or src.detail})")
        if self.systemic == "low":
            return (False, f"systemic exposure is LOW ({src.kind}: {src.citation or src.detail}) "
                           f"— sufficient to discuss minimal/incidental absorption, not to claim "
                           f"systemic activity")
        return (True, f"systemic exposure 'full' per {src.kind} ({src.citation or src.detail}), "
                      f"tier {src.tier.value}")

    def supports_responder_claim(self) -> tuple:
        """A responder definition / trial population is a systemic claim
        (CLAUDE.md §5: a systemic responder definition for a face mask is a
        category error). Same gate, reported in responder language."""
        ok, why = self.supports_systemic_claim()
        if ok:
            return (True, f"systemic trial population admissible: {why}")
        return (False, f"no systemic responder population admissible: {why}. "
                       f"Reframe to local delivery in {', '.join(self.primary_compartments) or 'no sourced compartment'}.")

    def supports_cns_claim(self) -> tuple:
        src = self.field_sources.get("cns")
        if src is None:
            return (False, "CNS access not determined")
        if src.is_rule_of_thumb:
            return (False, f"CNS access rests only on a rule-of-thumb default ({src.tier.value})")
        if self.cns == "unlikely":
            return (False, f"CNS access unlikely per {src.kind} ({src.citation or src.detail})")
        if self.cns == "possible":
            return (False, f"CNS access only 'possible' per {src.kind} "
                           f"({src.citation or src.detail}) — hypothesis, not a claim")
        return (True, f"CNS access per {src.kind} ({src.citation or src.detail})")

    def to_dict(self) -> dict:
        return {
            "compound": self.compound,
            "modality": self.modality,
            "route": self.route,
            "formulation": self.formulation,
            "formulation_in_vocab": self.formulation_in_vocab,
            "primary_compartments": list(self.primary_compartments),
            "systemic": self.systemic,
            "cns": self.cns,
            "provisional": self.provisional,
            "provisional_fields": self.provisional_fields,
            "field_sources": {k: v.to_dict() for k, v in self.field_sources.items()},
            "tiers": {f: self.tier_of(f).value for f in PROFILE_FIELDS},
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #


def _resolve_field(candidates: Iterable[Observation]):
    """Highest source priority wins; ties broken by the stronger tier, then by
    order of supply. Returns (value, FieldSource) or None."""
    cands = list(candidates)
    if not cands:
        return None
    best = min(cands, key=lambda o: (o.source.priority, -_tier_rank(o.source.tier)))
    return (best.value, best.source)


_TIER_RANK = {Tier.E0: 5, Tier.E1: 4, Tier.E3: 3, Tier.E2: 2, Tier.E4: 1, Tier.REJECT: 0}


def _tier_rank(t: Tier) -> int:
    return _TIER_RANK.get(t, 0)


def build_profile(modality, route, formulation=None, observations: Iterable[Observation] = (),
                  compound: str = "", notes: Optional[list] = None) -> ExposureProfile:
    """Build an ExposureProfile from modality x route x formulation plus any
    sourced observations.

    Every field not covered by an observation falls back to this module's
    rule-of-thumb route default, which is recorded as a `rule_of_thumb`
    (**E4**) source — making the profile `provisional` for that field (B6).
    """
    mod = normalize_modality(modality)
    rt = normalize_route(route)
    form, in_vocab = normalize_formulation(formulation)
    notes = list(notes or [])
    if not in_vocab and form:
        notes.append(f"formulation '{form}' is free text, not in the controlled vocabulary")
    if rt is Route.OTHER and _norm(route) not in ("", "other", "unknown", None):
        notes.append(f"route '{route}' not in the route vocabulary — treated as 'other'; "
                     f"exposure is not assessable until the route is resolved")

    comps_default, systemic_default, cns_default = ROUTE_DEFAULTS[rt]
    comps_default = list(comps_default)
    rot_detail = f"route default for {rt.value} (no molecule-specific source supplied)"
    if mod in _MACROMOLECULES and rt is Route.ORAL:
        systemic_default = "none"
        rot_detail = (f"route default for {rt.value} with modality {mod.value}: macromolecules are "
                      f"degraded/not absorbed from the gut without an enabling delivery system")

    by_field = {f: [] for f in PROFILE_FIELDS}
    for obs in observations or ():
        by_field[obs.field].append(obs)

    defaults = {
        "primary_compartments": comps_default,
        "systemic": systemic_default,
        "cns": cns_default,
    }
    values, sources = {}, {}
    for fld in PROFILE_FIELDS:
        got = _resolve_field(by_field[fld])
        if got is None:
            values[fld] = defaults[fld]
            sources[fld] = rule_of_thumb_source(rot_detail)
        else:
            values[fld], sources[fld] = got

    return ExposureProfile(
        modality=mod.value, route=rt.value, formulation=form,
        primary_compartments=list(values["primary_compartments"]),
        systemic=values["systemic"], cns=values["cns"],
        field_sources=sources, compound=compound,
        formulation_in_vocab=in_vocab, notes=notes,
    )


def herbal_formula_profile(formula: str, route, source: str, source_detail: str = "",
                           formulation=None, compartments: Optional[list] = None,
                           notes: Optional[list] = None) -> ExposureProfile:
    """Formula-level exposure profile for a herbal formula (design §8.2 B6).

    The route recorded in a classical or pharmacopoeia source is a legitimate
    **E1** source for the *compartment* the preparation is applied to, and it
    propagates to the constituents (`constituent_profile`). It says nothing about
    any constituent's systemic exposure, so `systemic` is left on the
    rule-of-thumb default and the profile stays `provisional` for that field.

    `source` is the cited text (e.g. "太平聖惠方 (七白膏) — 外用"); it must be a real,
    checkable reference and is carried into the report unchanged.
    """
    if not (source or "").strip():
        raise ValueError("a herbal formula-level route needs its classical/pharmacopoeia "
                         "citation — an unsourced route is not E1 (design §8.2 B6)")
    rt = normalize_route(route)
    comps = list(compartments) if compartments else list(ROUTE_DEFAULTS[rt][0])
    obs = [Observation("primary_compartments", comps,
                       classical_source(source, source_detail or
                                        f"formula-level route of administration for {formula}"))]
    prof = build_profile(Modality.HERBAL_FORMULA, rt, formulation, obs, compound=formula,
                         notes=notes)
    prof.notes.append(
        "formula-level route is E1 for the compartment and propagates to constituents; "
        "constituent-level systemic exposure stays provisional until that constituent has "
        "its own PK (design §8.2 B6)")
    prof.notes.append(
        "a database compound list is not the extract: constituent identity and abundance "
        "require LC-MS of the preparation actually used (CLAUDE.md §4 Step 0)")
    return prof


def constituent_profile(formula_profile: ExposureProfile, constituent: str,
                        own_pk: Optional[Observation] = None,
                        modality=Modality.SMALL_MOLECULE) -> ExposureProfile:
    """Derive a constituent's profile from its formula's (design §8.2 B6).

    The compartment is inherited **with the formula's source and tier** (E1 when
    the formula route came from a classical/pharmacopoeia text). Systemic exposure
    is NOT inherited: it stays on the rule-of-thumb default — i.e. provisional —
    unless `own_pk` supplies a constituent-specific sourced observation.
    """
    comp_src = formula_profile.source_of("primary_compartments") or rule_of_thumb_source(
        "inherited from formula profile with no source")
    obs = [Observation("primary_compartments", list(formula_profile.primary_compartments),
                       comp_src)]
    if own_pk is not None:
        obs.append(own_pk)
    prof = build_profile(modality, formula_profile.route, formula_profile.formulation,
                         obs, compound=constituent)
    prof.notes.append(f"compartment inherited from formula '{formula_profile.compound}' "
                      f"({comp_src.kind}, tier {comp_src.tier.value})")
    if own_pk is None:
        prof.notes.append("no constituent-specific PK supplied — systemic exposure is "
                          "provisional (E4) and cannot support a systemic or responder claim")
    return prof


# --------------------------------------------------------------------------- #
# target-tissue reachability (design §8.2 B3)
# --------------------------------------------------------------------------- #


@dataclass
class Reachability:
    verdict: str                    # see the four module constants
    reachable: bool
    tissue: str
    target_compartment: Optional[str]
    route_compartments: list = field(default_factory=list)
    via: str = ""                   # "direct" | "systemic" | ""
    sources: list = field(default_factory=list)     # FieldSource
    provisional: bool = False
    rationale: list = field(default_factory=list)

    @property
    def is_mismatch(self) -> bool:
        return self.verdict == NOT_DELIVERABLE_TO_TARGET_TISSUE

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reachable": self.reachable, "tissue": self.tissue,
                "target_compartment": self.target_compartment,
                "route_compartments": list(self.route_compartments), "via": self.via,
                "provisional": self.provisional,
                "sources": [s.to_dict() for s in self.sources],
                "rationale": list(self.rationale)}


def reaches_target_tissue(profile: ExposureProfile, tissue: str) -> Reachability:
    """Does this route, in this formulation, put the molecule where the pathology is?

    Delivery feasibility is judged against the **tissue of pathology**, not the
    route's own compartment (design §8.2 B3). Four outcomes:

      * `reachable_direct`   — the tissue is one of the route's own compartments.
      * `reachable_systemic` — the tissue is perfused and the profile has
        **full** systemic exposure (barrier-restricted compartments additionally
        need their own field: `cns`/`csf` need `cns`, the eye needs an explicit
        compartment). `systemic == 'low'` does **not** reach a distal tissue: low
        means incidental absorption measured in plasma, not delivery of an active
        concentration to the pathology, so it yields a mismatch. This is what
        separates "ruxolitinib cream is absorbed a little" from "ruxolitinib cream
        treats marrow disease", and it is the same threshold
        `supports_systemic_claim()` applies.
      * `not_deliverable_to_target_tissue` — the route cannot reach it. Step 0
        raises **EXPOSURE_MISMATCH** on this and stops before Step 1.
      * `not_assessable` — the tissue could not be mapped onto the compartment
        vocabulary, or the route is unresolved. Never silently a pass.
    """
    comp = resolve_compartment(tissue)
    route_comps = list(profile.primary_compartments)
    comp_src = profile.source_of("primary_compartments")
    sys_src = profile.source_of("systemic")
    cns_src = profile.source_of("cns")
    srcs = [s for s in (comp_src,) if s]

    if comp is None:
        return Reachability(
            NOT_ASSESSABLE, False, str(tissue), None, route_comps, "", srcs,
            profile.provisional,
            [f"tissue of pathology '{tissue}' does not map onto the compartment vocabulary "
             f"({len(COMPARTMENTS)} tokens) — resolve it before judging delivery; "
             f"not assessable is not a pass"])

    if not route_comps:
        return Reachability(
            NOT_ASSESSABLE, False, str(tissue), comp, route_comps, "", srcs,
            profile.provisional,
            [f"route '{profile.route}' has no sourced compartments — exposure not assessable"])

    # 1. direct: the route puts the drug in that compartment
    if comp in route_comps:
        return Reachability(
            REACHABLE_DIRECT, True, str(tissue), comp, route_comps, "direct", srcs,
            comp_src.is_rule_of_thumb if comp_src else True,
            [f"'{tissue}' -> compartment '{comp}', which route '{profile.route}' reaches "
             f"directly ({comp_src.kind if comp_src else 'unsourced'}, "
             f"tier {(comp_src.tier.value if comp_src else 'E4')})"])

    rationale = [f"'{tissue}' -> compartment '{comp}'; route '{profile.route}' reaches "
                 f"{route_comps} directly, which does not include it"]

    # 2. luminal compartments are outside the barrier — systemic exposure never reaches them
    if comp in LUMINAL_COMPARTMENTS:
        rationale.append(f"'{comp}' is a luminal / outside-the-barrier compartment: it is reached "
                         f"only by applying the drug there, not from the circulation")
        return Reachability(NOT_DELIVERABLE_TO_TARGET_TISSUE, False, str(tissue), comp,
                            route_comps, "", srcs, profile.provisional, rationale)

    # 3. systemic route to a perfused compartment. 'low' is incidental absorption,
    #    not delivery: it does not reach a distal tissue of pathology.
    systemic_ok = profile.systemic == "full"
    if comp in BARRIER_RESTRICTED_COMPARTMENTS:
        if comp in ("cns", "csf"):
            if profile.cns == "yes" and cns_src is not None and systemic_ok:
                srcs.append(cns_src)
                rationale.append(f"CNS access 'yes' per {cns_src.kind} "
                                 f"({cns_src.citation or cns_src.detail})")
                return Reachability(REACHABLE_SYSTEMIC, True, str(tissue), comp, route_comps,
                                    "systemic", srcs,
                                    cns_src.is_rule_of_thumb, rationale)
            rationale.append(
                f"'{comp}' is behind the blood-brain barrier and the profile's cns field is "
                f"'{profile.cns}'"
                + (f" ({cns_src.kind})" if cns_src else "")
                + " — not established access")
            return Reachability(NOT_DELIVERABLE_TO_TARGET_TISSUE, False, str(tissue), comp,
                                route_comps, "", srcs, profile.provisional, rationale)
        rationale.append(f"'{comp}' is behind a blood-ocular barrier: systemic exposure does not "
                         f"establish access, and this route's compartments do not include it")
        return Reachability(NOT_DELIVERABLE_TO_TARGET_TISSUE, False, str(tissue), comp,
                            route_comps, "", srcs, profile.provisional, rationale)

    if comp in PERFUSED_COMPARTMENTS and systemic_ok:
        if sys_src:
            srcs.append(sys_src)
        prov = (sys_src.is_rule_of_thumb if sys_src else True)
        rationale.append(
            f"'{comp}' is perfused and systemic exposure is '{profile.systemic}' per "
            f"{sys_src.kind if sys_src else 'unsourced'} "
            f"(tier {(sys_src.tier.value if sys_src else 'E4')}) -> reached via the circulation")
        if prov:
            rationale.append("systemic exposure rests on a rule-of-thumb default (E4): the "
                             "reachability is provisional and cannot carry a systemic claim")
        return Reachability(REACHABLE_SYSTEMIC, True, str(tissue), comp, route_comps,
                            "systemic", srcs, prov, rationale)

    if sys_src:
        srcs.append(sys_src)
    rationale.append(f"systemic exposure is '{profile.systemic}'"
                     + (f" per {sys_src.kind}" if sys_src else "")
                     + f" — no route from '{profile.route}' to '{comp}'")
    if profile.systemic == "low":
        rationale.append(
            "LOW systemic exposure is incidental absorption, not delivery: reaching "
            f"'{comp}' at a pharmacologically active concentration is NOT established. A "
            "systemic-efficacy claim here is a category error; if a delivery system or a "
            "different route could bridge the gap, route to the development path instead")
    return Reachability(NOT_DELIVERABLE_TO_TARGET_TISSUE, False, str(tissue), comp,
                        route_comps, "", srcs, profile.provisional, rationale)


def exposure_mismatch(profile: ExposureProfile, tissue: str) -> tuple:
    """Step-0 gate (design §8.2 B3) -> (is_mismatch, Reachability).

    True means Step 0 must return **EXPOSURE_MISMATCH**, write
    `HALT_exposure_mismatch.md` naming the route, its compartments, the tissue of
    pathology and the source for each, and stop before Step 1. Where a delivery
    system could plausibly bridge the gap, the stop report routes to the
    development path instead of claiming systemic efficacy.
    """
    r = reaches_target_tissue(profile, tissue)
    return (r.is_mismatch, r)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    # 1. ruxolitinib cream (label-sourced skin-only profile) vs two pathologies
    cream = build_profile(
        Modality.SMALL_MOLECULE, Route.TOPICAL_SKIN, "cream",
        observations=[
            Observation("systemic", "low",
                        label_source("DailyMed SPL 24da5509-6631-4795-9d42-273faecd08e7",
                                     "OPZELURA (ruxolitinib) cream — label route + clinical pharmacology")),
        ],
        compound="ruxolitinib")
    for tissue in ("lesional skin", "bone marrow"):
        mm, r = exposure_mismatch(cream, tissue)
        print(f"ruxolitinib cream -> {tissue:14s} {r.verdict:34s} mismatch={mm}")
    print("  systemic claim:", cream.supports_systemic_claim())

    # 2. herbal formula: formula-level E1 compartment, provisional constituent systemic
    qbs = herbal_formula_profile("七白散 (Qibai San)", "topical",
                                 "太平聖惠方 (七白膏); 永類鈐方 (洗面七白散) — 外用美白祛斑",
                                 formulation="mask")
    print("\nformula compartment tier:", qbs.tier_of("primary_compartments").value,
          "| systemic tier:", qbs.tier_of("systemic").value, "| provisional:", qbs.provisional)
    imp = constituent_profile(qbs, "imperatorin")
    print("constituent compartment tier:", imp.tier_of("primary_compartments").value,
          "| systemic:", imp.supports_systemic_claim()[0], "|", imp.provisional_fields)
