"""Delivery feasibility (v12) — can this molecule be delivered by this route, and
if not, is there a precedented delivery system that would make it possible?

Design: `docs/superpowers/specs/2026-11-10-moa-kernel-design.md` §4.5, §8.2 B4.

v11 asked one yes/no question with one rule set ("does it clear the topical or the
oral window?") and treated a failure as a dead end. For a research service that is
the wrong answer twice over: it had no rule for peptides, antibodies, inhaled or
ophthalmic drugs, and it discarded exactly the compounds whose mechanism may be
real and reachable with an enabling delivery system — a development path, not a
dead end.

    assess_delivery(compound, route, modality=..., formulation=..., precedents=...)
    screen_delivery(compounds, route, modality=..., ...)     -> {name: Feasibility}

**Four levels** (design §4.5, G4):

    as_is           deliverable by this route as a conventional formulation
    dds_enabled     NOT deliverable conventionally, but a delivery system with
                    **precedent at E1 or better** makes it plausible. Such a
                    compound STAYS in the analysis and may anchor a hub, but every
                    mechanism it anchors is `delivery_dependent` and the Bottom
                    line may not rest on it alone (design §8.2 B4 — this replaces
                    CLAUDE.md §3.4's blanket "may not anchor a mechanism").
    not_deliverable no precedent at E1+. An analogy-only (E4) suggestion does NOT
                    license `dds_enabled`; it is recorded as a speculative note and
                    the level stays `not_deliverable` (§8.2 B4, which is what keeps
                    this level reachable at all).
    not_assessable  no rule set and no precedent for this (modality, route), or the
                    descriptors needed are missing. Never a silent pass.

**Rule sets are keyed by (modality, route)** and every threshold carries its
citation (see CITATIONS below). Where a threshold is widely used but could not be
grounded at claim level in a source we verified, it is marked **provisional** and
says so in `Feasibility.sources` / `.note` — a rule of thumb is reported as one,
never dressed as a measured cutoff.

**Precedence rule.** An approved product of *that molecule* by *that route* settles
the question, whatever the rule of thumb says, citing the label (design §4.5):

  * approved product with no enabling technology -> `as_is`. Tacrolimus ointment
    (MW 804, PROTOPIC) is the worked example: it violates the 500 Da skin rule and
    is nonetheless an approved topical product, so the rule loses.
  * approved product that *is* an enabling delivery system -> `dds_enabled`, with
    the product as its precedent. Oral semaglutide (RYBELSUS, co-formulated with
    the permeation enhancer SNAC) is the worked example: it is not orally
    deliverable as a plain tablet, and the approval proves the DDS path works.

**Parenteral routes** (SC/IM/IV/intra-articular/intrathecal): absorption rules do
not apply — the drug is placed inside the body — so the level is `as_is` for
systemic exposure, with label bioavailability noted where a label is on file.

v11 COMPATIBILITY (design §4.5, §6): `topical_feasible` / `oral_feasible` /
`assess` / `screen` are preserved **verbatim** as a compatibility layer, including
their note strings and their `.route` / `.feasible` / `.violations` / `.note`
attributes, so shipped v11 run scripts keep working and keep their old answers.
They do not consult precedents and are not routed through the new levels; they only
additionally expose `.level` for new consumers. New code should call
`assess_delivery`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Optional

from .evidence_schema import Tier
from .exposure import (
    PARENTERAL_ROUTES,
    Modality,
    Route,
    normalize_formulation,
    normalize_modality,
    normalize_route,
)


class Level(str, Enum):
    AS_IS = "as_is"
    DDS_ENABLED = "dds_enabled"
    NOT_DELIVERABLE = "not_deliverable"
    NOT_ASSESSABLE = "not_assessable"


# --------------------------------------------------------------------------- #
# citations
#
# Every record below was resolved against NCBI eutils / DailyMed on 2026-11-10
# (PMID or SPL setid, title, journal, volume, pages). `grounded=True` means the
# cited source is the source OF THAT THRESHOLD; `provisional=True` marks a
# threshold that is in common use but that we could NOT ground at claim level in
# a source we verified — it is reported as a rule of thumb, with the reason.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Citation:
    ref: str                        # PMID:… / DOI / DailyMed SPL setid
    text: str                       # rendered reference
    tier: Tier = Tier.E1
    grounded: bool = False
    provisional: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {"ref": self.ref, "text": self.text, "tier": self.tier.value,
                "grounded": self.grounded, "provisional": self.provisional,
                "note": self.note}


CITE_LIPINSKI = Citation(
    "PMID:11259830",
    "Lipinski, C. A., Lombardo, F., Dominy, B. W., & Feeney, P. J. (2001). Experimental and "
    "computational approaches to estimate solubility and permeability in drug discovery and "
    "development settings. Advances in Drug Delivery Reviews, 46(1-3), 3-26.",
    Tier.E1, grounded=True,
    note="Rule of 5 (MW<=500, LogP<=5, HBD<=5, HBA<=10; >=2 violations predict poor "
         "absorption/permeation) is this paper's own rule. Record verified via NCBI eutils.")

CITE_VEBER = Citation(
    "PMID:12036371",
    "Veber, D. F., Johnson, S. R., Cheng, H. Y., Smith, B. R., Ward, K. W., & Kopple, K. D. "
    "(2002). Molecular properties that influence the oral bioavailability of drug candidates. "
    "Journal of Medicinal Chemistry, 45(12), 2615-2623.",
    Tier.E1, grounded=True,
    note="TPSA<=140 A^2 and rotatable bonds<=10 are this paper's own findings. Record verified "
         "via NCBI eutils.")

CITE_BOS_500DA = Citation(
    "PMID:10839713",
    "Bos, J. D., & Meinardi, M. M. (2000). The 500 Dalton rule for the skin penetration of "
    "chemical compounds and drugs. Experimental Dermatology, 9(3), 165-169.",
    Tier.E1, grounded=True,
    note="The MW<=500 Da skin-penetration cutoff is the paper's titular claim. Record verified "
         "via NCBI eutils.")

CITE_NAIK_SKIN = Citation(
    "PMID:10996573",
    "Naik, A., Kalia, Y. N., & Guy, R. H. (2000). Transdermal drug delivery: overcoming the "
    "skin's barrier function. Pharmaceutical Science & Technology Today, 3(9), 318-326. "
    "https://doi.org/10.1016/s1461-5347(00)00295-9",
    Tier.E1, grounded=False, provisional=True,
    note="PROVISIONAL THRESHOLD. Record verified via NCBI eutils, and the paper grounds the "
         "existence of approaches that overcome the skin barrier (its title). It does NOT state "
         "the LogP ~1-3 permeation window in its abstract, so that numeric window is reported "
         "here as an ungrounded rule of thumb, not as a cited cutoff.")

CITE_YOSHIDA_CORNEA = Citation(
    "PMID:8863270",
    "Yoshida, F., & Topliss, J. G. (1996). Unified model for the corneal permeability of related "
    "and diverse compounds with respect to their physicochemical properties. Journal of "
    "Pharmaceutical Sciences, 85(8), 819-823. https://doi.org/10.1021/js960076m",
    Tier.E1, grounded=True,
    note="Abstract verified: corneal permeability shows a PARABOLIC relationship with "
         "lipophilicity (log P) within compound classes, with delta log P as the unifying "
         "variable. This grounds the EXISTENCE of a corneal lipophilicity optimum; the specific "
         "numeric window used below is provisional (see CITE_CORNEAL_WINDOW).")

CITE_PRAUSNITZ_EYE = Citation(
    "PMID:10189253",
    "Prausnitz, M. R., & Noonan, J. S. (1998). Permeability of cornea, sclera, and conjunctiva: "
    "a literature analysis for drug delivery to the eye. Journal of Pharmaceutical Sciences, "
    "87(12), 1479-1488.",
    Tier.E1, grounded=False,
    note="Record verified via NCBI eutils (title/journal/volume/pages). Cited as the literature "
         "analysis of ocular-tissue permeability behind the ophthalmic rule set; the numeric "
         "window below is not attributed to it.")

CITE_CORNEAL_WINDOW = Citation(
    "", "No verified source for the specific numeric corneal-permeation window "
        "(MW <= 500 Da, LogP ~1-3).",
    Tier.E4, grounded=False, provisional=True,
    note="PROVISIONAL THRESHOLD, DELIBERATELY UNCITED. The parabolic lipophilicity relationship "
         "is grounded (CITE_YOSHIDA_CORNEA) but we could not ground these numbers at claim "
         "level in a source we verified. Reported as a flag, never as a measured cutoff; "
         "an approved ophthalmic product overrides it (precedence rule).")

CITE_LABIRIS_LUNG = Citation(
    "PMID:14616418",
    "Labiris, N. R., & Dolovich, M. B. (2003). Pulmonary drug delivery. Part I: physiological "
    "factors affecting therapeutic effectiveness of aerosolized medications. British Journal of "
    "Clinical Pharmacology, 56(6), 588-599.",
    Tier.E1, grounded=True,
    note="Abstract verified: airway geometry, humidity, mucociliary clearance and alveolar "
         "macrophages are the barriers, and efficacy depends on WHERE in the respiratory tract "
         "the drug deposits. This grounds the flag-only treatment of inhaled delivery: "
         "deposition is governed by the aerosol/device, not by the molecule's MW or LogP.")

CITE_BITTNER_SC = Citation(
    "PMID:30043229",
    "Bittner, B., Richter, W., & Schmidt, J. (2018). Subcutaneous administration of "
    "biotherapeutics: an overview of current challenges and opportunities. BioDrugs, 32(5), "
    "425-440. https://doi.org/10.1007/s40259-018-0295-0",
    Tier.E1, grounded=False,
    note="Record verified via NCBI eutils. Cited as the review of what governs subcutaneous "
         "absorption (injection-site and lymphatic physiology); the claim this module makes from "
         "it — that oral-absorption descriptors do not apply to a parenteral route — is "
         "definitional for IV and well established for SC/IM, not a numeric threshold.")

CITE_BUCKLEY_SNAC = Citation(
    "PMID:30429357",
    "Buckley, S. T., Baekdal, T. A., Vegge, A., Maarbjerg, S. J., et al. (2018). Transcellular "
    "stomach absorption of a derivatized glucagon-like peptide-1 receptor agonist. Science "
    "Translational Medicine, 10(467), eaar7047. https://doi.org/10.1126/scitranslmed.aar7047",
    Tier.E1, grounded=True,
    note="Title/record verified via NCBI eutils: transcellular stomach absorption of a "
         "derivatized GLP-1 receptor agonist (semaglutide co-formulated with the permeation "
         "enhancer SNAC). Grounds the published precedent for oral peptide delivery.")

CITE_AUNGST_ENHANCERS = Citation(
    "PMID:22105442",
    "Aungst, B. J. (2012). Absorption enhancers: applications and advances. The AAPS Journal, "
    "14(1), 10-18. https://doi.org/10.1208/s12248-011-9307-4",
    Tier.E1, grounded=True,
    note="Title/record verified via NCBI eutils. Grounds the existence of the absorption-enhancer "
         "DDS class; it does not license any particular compound's level.")

# --- approved-product labels (DailyMed SPL setids resolved 2026-11-10) ------- #

CITE_LABEL_PROTOPIC = Citation(
    "DailyMed SPL 3b7f0fed-9046-4094-a131-29d560733e47",
    "PROTOPIC (tacrolimus) ointment [prescribing information]. DailyMed, U.S. National Library "
    "of Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "3b7f0fed-9046-4094-a131-29d560733e47",
    Tier.E0, grounded=True,
    note="SPL record resolved via the DailyMed v2 API. Tacrolimus MW 804.0 (PubChem CID 445643).")

CITE_LABEL_OPZELURA = Citation(
    "DailyMed SPL 24da5509-6631-4795-9d42-273faecd08e7",
    "OPZELURA (ruxolitinib) cream [prescribing information]. DailyMed, U.S. National Library of "
    "Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "24da5509-6631-4795-9d42-273faecd08e7",
    Tier.E0, grounded=True, note="SPL record resolved via the DailyMed v2 API.")

CITE_LABEL_RYBELSUS = Citation(
    "DailyMed SPL 27f15fac-7d98-4114-a2ec-92494a91da98",
    "RYBELSUS (semaglutide) tablets [prescribing information]. DailyMed, U.S. National Library "
    "of Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "27f15fac-7d98-4114-a2ec-92494a91da98",
    Tier.E0, grounded=True,
    note="SPL record resolved via the DailyMed v2 API (oral semaglutide tablet). Semaglutide "
         "MW 4114 (PubChem CID 56843331); oral delivery depends on the co-formulated permeation "
         "enhancer SNAC, i.e. an enabling delivery system.")

CITE_LABEL_MYCAPSSA = Citation(
    "DailyMed SPL 58d80bc6-bdfb-4908-93e7-aace447c8d1a",
    "MYCAPSSA (octreotide) delayed-release capsules [prescribing information]. DailyMed, U.S. "
    "National Library of Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "58d80bc6-bdfb-4908-93e7-aace447c8d1a",
    Tier.E0, grounded=True,
    note="SPL record resolved via the DailyMed v2 API. Octreotide MW 1019.2 (PubChem CID "
         "448601) delivered orally via an enabling oral-peptide technology.")

CITE_LABEL_LEQVIO = Citation(
    "DailyMed SPL 6fc0afca-4513-4c35-b594-6544aee29a44",
    "LEQVIO (inclisiran) injection [prescribing information]. DailyMed, U.S. National Library of "
    "Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "6fc0afca-4513-4c35-b594-6544aee29a44",
    Tier.E0, grounded=True, note="SPL record resolved via the DailyMed v2 API.")

CITE_LABEL_LIPITOR = Citation(
    "DailyMed SPL a60cc18b-0631-4cf0-b021-9f52224ece65",
    "LIPITOR (atorvastatin calcium) tablets [prescribing information]. DailyMed, U.S. National "
    "Library of Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "a60cc18b-0631-4cf0-b021-9f52224ece65",
    Tier.E0, grounded=True, note="SPL record resolved via the DailyMed v2 API.")

CITE_LABEL_XALATAN = Citation(
    "DailyMed SPL a98595b3-9f47-48e0-b18d-550a2095f264",
    "XALATAN (latanoprost) ophthalmic solution [prescribing information]. DailyMed, U.S. "
    "National Library of Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "a98595b3-9f47-48e0-b18d-550a2095f264",
    Tier.E0, grounded=True, note="SPL record resolved via the DailyMed v2 API.")

CITE_LABEL_SPIRIVA = Citation(
    "DailyMed SPL 820839ef-e53d-47e8-a3b9-d911ff92e6a9",
    "SPIRIVA HANDIHALER (tiotropium bromide) inhalation powder [prescribing information]. "
    "DailyMed, U.S. National Library of Medicine. https://dailymed.nlm.nih.gov/dailymed/"
    "drugInfo.cfm?setid=820839ef-e53d-47e8-a3b9-d911ff92e6a9",
    Tier.E0, grounded=True, note="SPL record resolved via the DailyMed v2 API.")

CITE_LABEL_DUPIXENT = Citation(
    "DailyMed SPL 595f437d-2729-40bb-9c62-c8ece1f82780",
    "DUPIXENT (dupilumab) injection [prescribing information]. DailyMed, U.S. National Library "
    "of Medicine. https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid="
    "595f437d-2729-40bb-9c62-c8ece1f82780",
    Tier.E0, grounded=True, note="SPL record resolved via the DailyMed v2 API.")


# --------------------------------------------------------------------------- #
# precedents
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Precedent:
    """An approved product or a published study showing this route works.

    `dds_class is None` means the product is delivered with no enabling delivery
    technology — that is what makes a molecule `as_is` despite a failed rule of
    thumb. A `dds_class` means the product/study *is* the enabling technology, and
    the molecule is `dds_enabled`, not `as_is`.

    `similar_molecule=True` marks a precedent for a DIFFERENT but similar molecule.
    Similarity is the caller's assertion, never this module's: the registry only
    holds exact-molecule precedents, so nothing is silently generalised.
    """
    modality: str
    route: str
    kind: str                       # "approved_product" | "published_study" | "analogy"
    citation: Citation
    molecule: str = ""
    product: str = ""
    dds_class: Optional[str] = None
    similar_molecule: bool = False
    note: str = ""

    @property
    def tier(self) -> Tier:
        return self.citation.tier

    @property
    def licenses_dds(self) -> bool:
        """E1 or better licenses `dds_enabled` (design §8.2 B4). An analogy-only
        (E4) precedent does not, however plausible it sounds."""
        return self.kind in ("approved_product", "published_study") and \
            self.tier in (Tier.E0, Tier.E1)

    def to_dict(self) -> dict:
        return {"molecule": self.molecule, "modality": self.modality, "route": self.route,
                "kind": self.kind, "product": self.product, "dds_class": self.dds_class,
                "similar_molecule": self.similar_molecule, "tier": self.tier.value,
                "licenses_dds": self.licenses_dds, "citation": self.citation.to_dict(),
                "note": self.note}


def analogy(note: str, modality=Modality.OTHER, route=Route.OTHER) -> Precedent:
    """Build an analogy-only (E4) 'precedent'. It is recorded as a speculative note
    and does NOT license `dds_enabled` (design §8.2 B4)."""
    return Precedent(normalize_modality(modality).value, normalize_route(route).value,
                     "analogy",
                     Citation("", f"Analogy only (no product, no study): {note}", Tier.E4,
                              grounded=False, provisional=True),
                     note=note)


#: Exact-molecule approved-product precedents. Extend as runs verify new labels;
#: every entry needs a resolvable label identifier.
PRODUCT_PRECEDENTS = (
    Precedent(Modality.SMALL_MOLECULE.value, Route.TOPICAL_SKIN.value, "approved_product",
              CITE_LABEL_PROTOPIC, molecule="tacrolimus", product="PROTOPIC ointment 0.03%/0.1%",
              dds_class=None,
              note="MW 804 violates the 500 Da skin rule, yet it is an approved topical "
                   "product — the worked precedence case of design §4.5."),
    Precedent(Modality.SMALL_MOLECULE.value, Route.TOPICAL_SKIN.value, "approved_product",
              CITE_LABEL_OPZELURA, molecule="ruxolitinib", product="OPZELURA cream 1.5%",
              dds_class=None),
    Precedent(Modality.PEPTIDE.value, Route.ORAL.value, "approved_product",
              CITE_LABEL_RYBELSUS, molecule="semaglutide", product="RYBELSUS tablets",
              dds_class="co-formulated permeation enhancer (SNAC)",
              note="Oral delivery of a 4.1 kDa peptide is achieved only with the enabling "
                   "permeation enhancer, so the level is dds_enabled, not as_is."),
    Precedent(Modality.PEPTIDE.value, Route.ORAL.value, "approved_product",
              CITE_LABEL_MYCAPSSA, molecule="octreotide",
              product="MYCAPSSA delayed-release capsules",
              dds_class="oral peptide delivery technology (transient permeability enhancer)"),
    Precedent(Modality.OLIGONUCLEOTIDE.value, Route.SUBCUTANEOUS.value, "approved_product",
              CITE_LABEL_LEQVIO, molecule="inclisiran", product="LEQVIO injection",
              dds_class="GalNAc conjugate (hepatocyte targeting)"),
    Precedent(Modality.SMALL_MOLECULE.value, Route.ORAL.value, "approved_product",
              CITE_LABEL_LIPITOR, molecule="atorvastatin", product="LIPITOR tablets",
              dds_class=None,
              note="Conventional tablet despite MW 558.6 and 12 rotatable bonds — the rule of "
                   "thumb loses to the label."),
    Precedent(Modality.SMALL_MOLECULE.value, Route.OPHTHALMIC.value, "approved_product",
              CITE_LABEL_XALATAN, molecule="latanoprost",
              product="XALATAN ophthalmic solution 0.005%", dds_class=None),
    Precedent(Modality.SMALL_MOLECULE.value, Route.INHALED.value, "approved_product",
              CITE_LABEL_SPIRIVA, molecule="tiotropium",
              product="SPIRIVA HANDIHALER inhalation powder", dds_class=None),
    Precedent(Modality.PROTEIN_ANTIBODY.value, Route.SUBCUTANEOUS.value, "approved_product",
              CITE_LABEL_DUPIXENT, molecule="dupilumab", product="DUPIXENT injection",
              dds_class=None),
)

#: Published precedents for a delivery CLASS. These are offered as candidates and
#: as references; on their own they do NOT license `dds_enabled` for an arbitrary
#: molecule — the caller must assert similarity by passing the precedent in with
#: `similar_molecule=True` (design §8.2 B4: precedent, not hand-waving).
PUBLISHED_CLASS_PRECEDENTS = (
    Precedent(Modality.PEPTIDE.value, Route.ORAL.value, "published_study", CITE_BUCKLEY_SNAC,
              dds_class="co-formulated permeation enhancer (SNAC)", similar_molecule=True,
              note="Transcellular stomach absorption of a derivatized GLP-1 agonist."),
    Precedent(Modality.SMALL_MOLECULE.value, Route.ORAL.value, "published_study",
              CITE_AUNGST_ENHANCERS, dds_class="absorption enhancer", similar_molecule=True),
    Precedent(Modality.SMALL_MOLECULE.value, Route.TOPICAL_SKIN.value, "published_study",
              CITE_NAIK_SKIN,
              dds_class="skin-barrier-overcoming formulation (chemical enhancer, vesicular "
                        "carrier or physical method)", similar_molecule=True),
)


@dataclass(frozen=True)
class DDSCandidate:
    """A candidate delivery-system class for a barrier. Advisory: it describes a
    direction, and only a `precedent` at E1+ licenses the `dds_enabled` level.

    The curated barrier x route -> DDS-class table with class-level parameters is
    design §4.7's `delivery_paths.py` and is deliberately NOT duplicated here.
    """
    dds_class: str
    barrier: str
    precedent: Optional[Precedent] = None
    provisional: bool = True
    note: str = ""

    @property
    def tier(self) -> Tier:
        return self.precedent.tier if self.precedent else Tier.E4

    def to_dict(self) -> dict:
        return {"dds_class": self.dds_class, "barrier": self.barrier,
                "tier": self.tier.value, "provisional": self.provisional,
                "precedent": self.precedent.to_dict() if self.precedent else None,
                "note": self.note}


def _skin_dds_candidates(violations: list) -> list:
    barrier = "; ".join(violations) or "stratum corneum"
    pre = PUBLISHED_CLASS_PRECEDENTS[2]
    return [
        DDSCandidate("chemical permeation enhancer", barrier, pre, True),
        DDSCandidate("nanoemulsion / microemulsion", barrier, None, True),
        DDSCandidate("liposome / ethosome (vesicular carrier)", barrier, None, True),
        DDSCandidate("microneedle array (barrier bypass)", barrier, None, True,
                     note="class-level parameters and precedent belong to delivery_paths.py"),
    ]


def _oral_macromolecule_dds_candidates(modality: Modality) -> list:
    barrier = ("gastrointestinal enzymatic degradation + epithelial tight junctions "
               "(macromolecule given by mouth)")
    pre = PUBLISHED_CLASS_PRECEDENTS[0] if modality is Modality.PEPTIDE else None
    return [
        DDSCandidate("co-formulated permeation enhancer (e.g. SNAC, SMPI)", barrier, pre, True),
        DDSCandidate("enteric / delayed-release protection", barrier, None, True),
        DDSCandidate("lipid or polymeric nanocarrier", barrier, None, True),
    ]


def _oral_small_molecule_dds_candidates(violations: list) -> list:
    barrier = "; ".join(violations) or "gastrointestinal absorption"
    return [
        DDSCandidate("absorption enhancer", barrier, PUBLISHED_CLASS_PRECEDENTS[1], True),
        DDSCandidate("amorphous solid dispersion / particle-size reduction", barrier, None, True),
        DDSCandidate("lipid-based formulation (SEDDS)", barrier, None, True),
        DDSCandidate("prodrug", barrier, None, True),
    ]


# --------------------------------------------------------------------------- #
# rule sets, keyed by (modality, route)
# --------------------------------------------------------------------------- #


def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _props(compound) -> dict:
    if isinstance(compound, str):
        return {"name": compound}
    return dict(compound or {})


def _lipinski_violations(p: dict) -> list:
    mw, logp = _num(p.get("mw")), _num(p.get("logp"))
    hbd, hba = _num(p.get("hbd")), _num(p.get("hba"))
    v = []
    if mw is not None and mw > 500:
        v.append(f"MW {mw:.0f} > 500 (Lipinski Ro5)")
    if logp is not None and logp > 5:
        v.append(f"LogP {logp} > 5 (Lipinski Ro5)")
    if hbd is not None and hbd > 5:
        v.append(f"HBD {hbd:.0f} > 5 (Lipinski Ro5)")
    if hba is not None and hba > 10:
        v.append(f"HBA {hba:.0f} > 10 (Lipinski Ro5)")
    return v


def _veber_violations(p: dict) -> list:
    tpsa, rot = _num(p.get("tpsa")), _num(p.get("rotatable_bonds"))
    v = []
    if tpsa is not None and tpsa > 140:
        v.append(f"TPSA {tpsa:.0f} > 140 (Veber)")
    if rot is not None and rot > 10:
        v.append(f"rotatable bonds {rot:.0f} > 10 (Veber)")
    return v


def _check_oral_small_molecule(p: dict) -> list:
    return _lipinski_violations(p) + _veber_violations(p)


def _check_skin(p: dict) -> list:
    mw, logp = _num(p.get("mw")), _num(p.get("logp"))
    v = []
    if mw is not None and mw > 500:
        v.append(f"MW {mw:.0f} > 500 (500 Da skin-penetration rule; Bos & Meinardi 2000)")
    if logp is not None and logp < 1:
        v.append(f"LogP {logp} < 1 (too polar to partition into skin lipids; "
                 f"PROVISIONAL rule-of-thumb window)")
    if logp is not None and logp > 4:
        v.append(f"LogP {logp} > 4 (retained in stratum corneum, poor flux; "
                 f"PROVISIONAL rule-of-thumb window)")
    return v


def _check_ophthalmic(p: dict) -> list:
    mw, logp = _num(p.get("mw")), _num(p.get("logp"))
    v = []
    if mw is not None and mw > 500:
        v.append(f"MW {mw:.0f} > 500 (PROVISIONAL corneal-permeation window)")
    if logp is not None and (logp < 1 or logp > 3):
        v.append(f"LogP {logp} outside ~1-3 (corneal permeability is parabolic in "
                 f"lipophilicity; PROVISIONAL numeric window)")
    return v


@dataclass(frozen=True)
class RuleSet:
    name: str
    kind: str                       # descriptor | precedent_required | flag_only | not_applicable
    citations: tuple = ()
    checker: Optional[Callable] = None
    required_props: tuple = ()
    fail_at: int = 1                # number of violations at which the rule set fails
    note: str = ""
    provisional: bool = False


RS_ORAL_SMALL_MOLECULE = RuleSet(
    "small_molecule/oral: Lipinski Ro5 + Veber", "descriptor",
    (CITE_LIPINSKI, CITE_VEBER), _check_oral_small_molecule,
    required_props=("mw", "logp", "hbd", "hba"), fail_at=2,
    note="Fails at >=2 violations across the Ro5 and Veber descriptors, following Lipinski's "
         "own 'two or more' criterion; TPSA and rotatable bonds are tested when supplied.")

RS_SKIN = RuleSet(
    "skin (topical/transdermal): 500 Da rule + LogP window", "descriptor",
    (CITE_BOS_500DA, CITE_NAIK_SKIN), _check_skin,
    required_props=("mw", "logp"), fail_at=1,
    note="MW<=500 is grounded (Bos & Meinardi 2000). The LogP ~1-3 (0-4 tolerated) window is a "
         "PROVISIONAL rule of thumb — reported, not cited as a measured cutoff.",
    provisional=True)

RS_OPHTHALMIC = RuleSet(
    "small_molecule/ophthalmic: corneal-permeation window", "descriptor",
    (CITE_YOSHIDA_CORNEA, CITE_PRAUSNITZ_EYE, CITE_CORNEAL_WINDOW), _check_ophthalmic,
    required_props=("mw", "logp"), fail_at=1,
    note="The parabolic lipophilicity-permeability relationship is grounded; the numeric window "
         "is PROVISIONAL and uncited. An approved ophthalmic product overrides it.",
    provisional=True)

RS_INHALED = RuleSet(
    "inhaled: flag-only", "flag_only", (CITE_LABIRIS_LUNG,),
    note="Deposition is governed by the aerosol/device (aerodynamic diameter, airway geometry, "
         "mucociliary clearance), not by MW or LogP, so no molecular pass/fail is applied. "
         "Lung delivery is flagged for formulation review instead.")

RS_PARENTERAL = RuleSet(
    "parenteral (SC/IM/IV/IA/IT): absorption rules not applicable", "not_applicable",
    (CITE_BITTNER_SC,),
    note="The drug is placed inside the body, so oral/skin absorption descriptors do not apply. "
         "Level is as_is for systemic exposure; bioavailability is a label fact where a label "
         "is on file.")


def _rs_precedent_required(modality: Modality) -> RuleSet:
    return RuleSet(
        f"{modality.value}/oral: precedent required", "precedent_required",
        (CITE_BUCKLEY_SNAC, CITE_AUNGST_ENHANCERS),
        note="A macromolecule given by mouth is degraded in the gut and is not absorbed intact "
             "without an enabling delivery system. No descriptor rule applies: the level is "
             "dds_enabled only with precedent at E1+ (an approved product such as oral "
             "semaglutide/octreotide, or a published study delivering a similar molecule by "
             "this route), otherwise not_deliverable.")


RULE_SETS = {
    (Modality.SMALL_MOLECULE, Route.ORAL): RS_ORAL_SMALL_MOLECULE,
    (Modality.SMALL_MOLECULE, Route.TOPICAL_SKIN): RS_SKIN,
    (Modality.SMALL_MOLECULE, Route.TRANSDERMAL): RS_SKIN,
    (Modality.SMALL_MOLECULE, Route.OPHTHALMIC): RS_OPHTHALMIC,
    (Modality.SMALL_MOLECULE, Route.INHALED): RS_INHALED,
    # the 500 Da skin rule is a property of skin, not of the modality
    (Modality.PEPTIDE, Route.TOPICAL_SKIN): RS_SKIN,
    (Modality.PEPTIDE, Route.TRANSDERMAL): RS_SKIN,
    (Modality.PROTEIN_ANTIBODY, Route.TOPICAL_SKIN): RS_SKIN,
    (Modality.PROTEIN_ANTIBODY, Route.TRANSDERMAL): RS_SKIN,
    (Modality.OLIGONUCLEOTIDE, Route.TOPICAL_SKIN): RS_SKIN,
    (Modality.OLIGONUCLEOTIDE, Route.TRANSDERMAL): RS_SKIN,
    # macromolecules by mouth
    (Modality.PEPTIDE, Route.ORAL): _rs_precedent_required(Modality.PEPTIDE),
    (Modality.PROTEIN_ANTIBODY, Route.ORAL): _rs_precedent_required(Modality.PROTEIN_ANTIBODY),
    (Modality.OLIGONUCLEOTIDE, Route.ORAL): _rs_precedent_required(Modality.OLIGONUCLEOTIDE),
    (Modality.EXTRACELLULAR_VESICLE, Route.ORAL): _rs_precedent_required(
        Modality.EXTRACELLULAR_VESICLE),
    (Modality.CELL, Route.ORAL): _rs_precedent_required(Modality.CELL),
}
# every modality is parenteral-eligible
for _m in Modality:
    for _r in PARENTERAL_ROUTES:
        RULE_SETS[(_m, _r)] = RS_PARENTERAL
# a herbal formula is a mixture: its constituents are assessed, never the formula
for _r in Route:
    RULE_SETS.pop((Modality.HERBAL_FORMULA, _r), None)
RULE_SETS[(Modality.SMALL_MOLECULE, Route.OTHER)] = RuleSet(
    "unresolved route", "not_assessable", (),
    note="The route is not in the vocabulary; resolve it before judging delivery.")


# --------------------------------------------------------------------------- #
# result
# --------------------------------------------------------------------------- #


@dataclass
class Feasibility:
    """Design §4.5 result type, plus the v11 attributes the compatibility layer needs.

    `level` is the v12 verdict; `feasible` is the v11 boolean and is derived from
    the level when not supplied, so old callers reading `.feasible` / `.route` /
    `.violations` / `.note` keep working unchanged.
    """
    level: str = Level.NOT_ASSESSABLE
    violations: list = field(default_factory=list)
    rule_set: str = ""
    sources: list = field(default_factory=list)          # Citation
    dds_candidates: list = field(default_factory=list)   # DDSCandidate
    precedents: list = field(default_factory=list)       # Precedent
    route: str = ""
    modality: str = ""
    compound: str = ""
    note: str = ""
    flags: list = field(default_factory=list)
    feasible: Optional[bool] = None

    def __post_init__(self):
        if self.feasible is None:
            self.feasible = (self.level == Level.AS_IS)

    @property
    def delivery_dependent(self) -> bool:
        """True for a `dds_enabled` compound: it may anchor a hub, but the
        mechanism is labelled delivery-dependent and the Bottom line may not rest
        on it alone (design §8.2 B4)."""
        return self.level == Level.DDS_ENABLED

    @property
    def provisional_rules(self) -> list:
        return [c for c in self.sources if getattr(c, "provisional", False)]

    def to_dict(self) -> dict:
        return {"compound": self.compound, "level": str(getattr(self.level, "value", self.level)),
                "feasible": self.feasible, "route": self.route, "modality": self.modality,
                "rule_set": self.rule_set, "violations": list(self.violations),
                "flags": list(self.flags), "note": self.note,
                "sources": [c.to_dict() for c in self.sources],
                "precedents": [p.to_dict() for p in self.precedents],
                "dds_candidates": [d.to_dict() for d in self.dds_candidates]}


# --------------------------------------------------------------------------- #
# precedent lookup
# --------------------------------------------------------------------------- #


#: Tokens that may decorate a molecule name without changing which molecule it is:
#: salt/hydrate forms, and route or dosage-form words that labels carry.
_NAME_QUALIFIERS = frozenset({
    "oral", "topical", "inhaled", "injectable", "ophthalmic",
    "tablet", "tablets", "capsule", "capsules", "ointment", "cream", "gel", "solution",
    "suspension", "injection", "spray", "drops", "powder",
    "calcium", "sodium", "potassium", "magnesium", "bromide", "chloride", "citrate",
    "hydrochloride", "hcl", "acetate", "maleate", "besylate", "mesylate", "tartrate",
    "sulfate", "sulphate", "fumarate", "succinate", "phosphate",
    "monohydrate", "dihydrate", "trihydrate", "anhydrous", "hydrate",
})


def _name_tokens(name: str) -> tuple:
    toks = [t for t in re.split(r"[^a-z0-9]+", (name or "").strip().lower()) if t]
    core = [t for t in toks if t not in _NAME_QUALIFIERS]
    return tuple(core or toks)


def _name_matches(molecule: str, name: str) -> bool:
    """Does `name` denote `molecule`?

    Exact match after normalisation, allowing only salt/hydrate and dosage-form
    qualifiers to differ ("atorvastatin calcium", "oral semaglutide", "tacrolimus
    ointment" all match their molecule). A substring test is NOT used: it would
    let "not-tacrolimus-at-all" — or any name that merely contains a known
    molecule's name — inherit that molecule's approved-product precedence, which is
    exactly how a wrong `as_is` would enter a run unnoticed.
    """
    m, n = (molecule or "").strip().lower(), (name or "").strip().lower()
    if not m or not n:
        return False
    if m == n:
        return True
    return _name_tokens(m) == _name_tokens(n)


def find_precedents(name: str, route, modality=None,
                    extra: Iterable[Precedent] = ()) -> list:
    """Exact-molecule precedents for this route from the registry, plus any the
    caller supplies. Registry matching is by molecule name and route; the modality
    is checked only when given, so a mis-typed modality cannot hide a real label."""
    rt = normalize_route(route)
    out = []
    for p in PRODUCT_PRECEDENTS:
        if p.route != rt.value:
            continue
        if not _name_matches(p.molecule, name):
            continue
        if modality is not None and p.modality != normalize_modality(modality).value:
            continue
        out.append(p)
    for p in extra or ():
        if normalize_route(p.route) is rt or p.route == Route.OTHER.value:
            out.append(p)
        elif p.route == rt.value:
            out.append(p)
    return out


def _licensing_precedent(precedents: Iterable[Precedent], modality: Modality,
                         route: Route) -> Optional[Precedent]:
    """The first supplied precedent at E1+ that applies to this (modality, route).
    An analogy-only (E4) precedent never qualifies (design §8.2 B4)."""
    for p in precedents or ():
        if not p.licenses_dds:
            continue
        if p.route not in (route.value, Route.OTHER.value):
            continue
        if p.modality not in (modality.value, Modality.OTHER.value):
            continue
        return p
    return None


def resolve_rule_set(modality, route):
    """-> (RuleSet | None, reason). None means not assessable, with the reason."""
    mod, rt = normalize_modality(modality), normalize_route(route)
    if mod is Modality.HERBAL_FORMULA:
        return (None, "a herbal formula is a mixture, not a molecule: assess each constituent's "
                      "delivery feasibility individually (design §8.1 R3 — attribution, not a "
                      "yes/no on the formula)")
    if rt is Route.OTHER:
        return (None, f"route '{route}' is not in the route vocabulary — resolve the route "
                      f"before judging delivery")
    rs = RULE_SETS.get((mod, rt))
    if rs is not None:
        return (rs, "")
    if mod is Modality.OTHER:
        rs = RULE_SETS.get((Modality.SMALL_MOLECULE, rt))
        if rs is not None:
            return (rs, "")
    return (None, f"no rule set for (modality={mod.value}, route={rt.value}); molecular "
                  f"descriptors do not decide this combination. Supply an approved-product or "
                  f"published precedent, or treat delivery as an open question")


# --------------------------------------------------------------------------- #
# the v12 entry point
# --------------------------------------------------------------------------- #


def assess_delivery(compound, route, modality=Modality.SMALL_MOLECULE, formulation=None,
                    precedents: Iterable[Precedent] = (), cns_target: bool = False,
                    exposure_profile=None) -> Feasibility:
    """Three-level delivery feasibility for (compound, modality, route, formulation).

    `compound` is a name or a dict of `{name, mw, logp, hbd, hba, tpsa,
    rotatable_bonds}`. `precedents` are caller-asserted precedents (an approved
    product or a published study, optionally `similar_molecule=True`); use
    `analogy()` for an analogy, which is recorded and does not license a level.
    `exposure_profile` is an `exposure.ExposureProfile`; when given, its route,
    modality and formulation fill in anything not passed explicitly.
    """
    if exposure_profile is not None:
        route = route if route is not None else exposure_profile.route
        modality = modality if modality is not None else exposure_profile.modality
        formulation = formulation if formulation is not None else exposure_profile.formulation
    p = _props(compound)
    name = p.get("name") or (compound if isinstance(compound, str) else "")
    mod, rt = normalize_modality(modality), normalize_route(route)
    form, form_ok = normalize_formulation(formulation)
    flags = []
    if not form_ok and form:
        flags.append(f"formulation '{form}' is free text, not in the controlled vocabulary")

    base = dict(route=rt.value, modality=mod.value, compound=name, flags=flags)
    all_pre = find_precedents(name, rt, None, precedents)
    speculative = [x for x in all_pre if not x.licenses_dds]

    if cns_target:
        cns_state = getattr(exposure_profile, "cns", None)
        if mod is not Modality.SMALL_MOLECULE or cns_state == "unlikely":
            flags.append("cns_target_non_penetrant_modality: the target is in the CNS and this "
                         "modality/route is not an established CNS-penetrant combination — "
                         "flagged, not failed")

    rs, why = resolve_rule_set(mod, rt)

    # 1. precedence rule: an approved product of THIS molecule by THIS route wins.
    exact = [x for x in all_pre
             if x.kind == "approved_product" and not x.similar_molecule
             and _name_matches(x.molecule or name, name) and x.route == rt.value]
    if exact:
        pre = exact[0]
        viol = rs.checker(p) if (rs and rs.kind == "descriptor" and rs.checker) else []
        srcs = [pre.citation] + list(rs.citations if rs else ())
        if pre.dds_class is None:
            note = (f"approved product precedence: {pre.product or pre.molecule} by the "
                    f"{rt.value} route. The rule of thumb"
                    + (f" ({rs.name})" if rs else "")
                    + (f" is overridden — recorded violations: {'; '.join(viol)}" if viol
                       else " is not contradicted") + ".")
            if viol:
                flags.append("rule_of_thumb_overridden_by_approved_product")
            return Feasibility(Level.AS_IS, viol, (rs.name if rs else "precedence only"),
                               srcs, [], all_pre, note=note, **base)
        note = (f"approved product precedence WITH an enabling delivery system: "
                f"{pre.product or pre.molecule} delivers this molecule by the {rt.value} route "
                f"via {pre.dds_class}. Conventional delivery is not established, so the level is "
                f"dds_enabled, not as_is; mechanisms anchored here are delivery_dependent.")
        cand = [DDSCandidate(pre.dds_class, "approved for this molecule by this route", pre,
                             provisional=False)]
        return Feasibility(Level.DDS_ENABLED, viol, (rs.name if rs else "precedence only"),
                           srcs, cand, all_pre, note=note, **base)

    # 2. parenteral: absorption rules do not apply
    if rt in PARENTERAL_ROUTES:
        label = next((x for x in all_pre if x.kind == "approved_product"), None)
        srcs = [RS_PARENTERAL.citations[0]] + ([label.citation] if label else [])
        note = RS_PARENTERAL.note + (
            f" Label on file: {label.product} — read bioavailability from it."
            if label else " No label on file for this molecule by this route: state "
                          "bioavailability as unmeasured rather than assuming it.")
        return Feasibility(Level.AS_IS, [], RS_PARENTERAL.name, srcs, [], all_pre,
                           note=note, **base)

    # 3. no rule set
    if rs is None or rs.kind == "not_assessable":
        return Feasibility(Level.NOT_ASSESSABLE, [], (rs.name if rs else "none"),
                           list(rs.citations) if rs else [], [], all_pre,
                           note=why or (rs.note if rs else ""), **base)

    # 4. flag-only (inhaled)
    if rs.kind == "flag_only":
        flags.append("delivery decided by the device/aerosol, not by molecular descriptors")
        return Feasibility(Level.AS_IS, [], rs.name, list(rs.citations), [], all_pre,
                           note=rs.note, **base)

    # 5. precedent-required (macromolecule by mouth)
    if rs.kind == "precedent_required":
        lic = _licensing_precedent(all_pre, mod, rt)
        cand = _oral_macromolecule_dds_candidates(mod)
        if lic is not None:
            note = (f"no conventional oral delivery for a {mod.value}; precedent at "
                    f"{lic.tier.value} ({lic.kind}: {lic.product or lic.citation.ref}"
                    + (" — similar molecule" if lic.similar_molecule else "")
                    + f") licenses the delivery-system path via {lic.dds_class or 'a DDS'}. "
                      f"Mechanisms anchored here are delivery_dependent.")
            cand = [DDSCandidate(lic.dds_class or "enabling delivery system",
                                 "macromolecule given by mouth", lic, provisional=False)] + cand
            return Feasibility(Level.DDS_ENABLED, [], rs.name,
                               [lic.citation] + list(rs.citations), cand, all_pre,
                               note=note, **base)
        note = (f"no conventional oral delivery for a {mod.value} and NO precedent at E1 or "
                f"better for this (modality, route): not_deliverable. ")
        if speculative:
            note += ("Speculative, non-licensing notes recorded: "
                     + " | ".join(f"{s.kind} ({s.tier.value}): {s.note or s.citation.text}"
                                  for s in speculative)
                     + ". An analogy is not a precedent (design §8.2 B4).")
            flags.append("analogy_only_not_sufficient")
        else:
            note += ("Supply an approved product or a published study delivering a similar "
                     "molecule by this route to reach dds_enabled.")
        return Feasibility(Level.NOT_DELIVERABLE, [], rs.name, list(rs.citations), cand,
                           all_pre, note=note, **base)

    # 6. descriptor rule sets
    missing = [k for k in rs.required_props if _num(p.get(k)) is None]
    if missing:
        return Feasibility(Level.NOT_ASSESSABLE, [f"missing {', '.join(missing)}"], rs.name,
                           list(rs.citations), [], all_pre,
                           note=f"cannot assess: {', '.join(missing)} not supplied for "
                                f"'{name or 'compound'}'. Fetch the descriptors (PubChem/RDKit) "
                                f"rather than assuming deliverability.", **base)
    viol = rs.checker(p)
    if len(viol) < rs.fail_at:
        note = (f"clears {rs.name}" + (f" (minor: {'; '.join(viol)})" if viol else "")
                + (f". {rs.note}" if rs.provisional else ""))
        return Feasibility(Level.AS_IS, viol, rs.name, list(rs.citations), [], all_pre,
                           note=note, **base)

    if rt in (Route.TOPICAL_SKIN, Route.TRANSDERMAL):
        cand = _skin_dds_candidates(viol)
    elif rt is Route.ORAL:
        cand = _oral_small_molecule_dds_candidates(viol)
    else:
        cand = [DDSCandidate("route-appropriate enabling formulation", "; ".join(viol), None,
                             True, note="candidate classes for this route belong to "
                                        "delivery_paths.py (design §4.7)")]
    lic = _licensing_precedent(all_pre, mod, rt)
    if lic is not None:
        note = (f"fails {rs.name} ({'; '.join(viol)}), but precedent at {lic.tier.value} "
                f"({lic.kind}: {lic.product or lic.citation.ref}"
                + (" — similar molecule" if lic.similar_molecule else "")
                + f") licenses a delivery-system path via {lic.dds_class or 'a DDS'}. "
                  f"Mechanisms anchored here are delivery_dependent.")
        cand = [DDSCandidate(lic.dds_class or "enabling delivery system", "; ".join(viol), lic,
                             provisional=False)] + cand
        return Feasibility(Level.DDS_ENABLED, viol, rs.name,
                           [lic.citation] + list(rs.citations), cand, all_pre,
                           note=note, **base)

    note = (f"fails {rs.name} ({'; '.join(viol)}) and no precedent at E1 or better was supplied "
            f"for this (modality, route): not_deliverable. ")
    if speculative:
        note += ("Speculative, non-licensing notes recorded: "
                 + " | ".join(f"{s.kind} ({s.tier.value}): {s.note or s.citation.text}"
                              for s in speculative)
                 + ". An analogy is not a precedent (design §8.2 B4).")
        flags.append("analogy_only_not_sufficient")
    else:
        note += ("Candidate delivery classes are listed as directions to investigate, not as a "
                 "level: an approved product or a published study with a similar molecule by "
                 "this route is required to reach dds_enabled.")
    if rs.provisional:
        note += f" NOTE: {rs.note}"
    return Feasibility(Level.NOT_DELIVERABLE, viol, rs.name, list(rs.citations), cand,
                       all_pre, note=note, **base)


def screen_delivery(compounds: Iterable, route, modality=Modality.SMALL_MOLECULE, **kw) -> dict:
    """{name: Feasibility} for a list of compound dicts (v12 API)."""
    out = {}
    for c in compounds or ():
        f = assess_delivery(c, route, modality, **kw)
        out[f.compound or _props(c).get("name", "?")] = f
    return out


# --------------------------------------------------------------------------- #
# v11 COMPATIBILITY LAYER — behaviour frozen; do not "improve" it.
#
# These four functions are called by shipped v11 run scripts. Their verdicts,
# their `.route` / `.feasible` / `.violations` / `.note` values and their note
# strings are reproduced verbatim from v11. They do NOT consult precedents and
# they do NOT apply the v12 levels (only `.level` is added, derived). New code
# calls `assess_delivery`.
# --------------------------------------------------------------------------- #

_V11_TOPICAL_SRCS = (CITE_BOS_500DA, CITE_NAIK_SKIN)
_V11_ORAL_SRCS = (CITE_LIPINSKI,)


def _v11(route: str, feasible: bool, violations: list, note: str, srcs=()) -> Feasibility:
    if note == "cannot assess":
        level = Level.NOT_ASSESSABLE
    else:
        level = Level.AS_IS if feasible else Level.NOT_DELIVERABLE
    return Feasibility(level=level, violations=violations, rule_set=f"v11-compat:{route}",
                       sources=list(srcs), dds_candidates=[], precedents=[],
                       route=route, note=note, feasible=feasible)


def topical_feasible(mw, logp) -> Feasibility:
    """v11 API, unchanged. Topical window: MW<=500 AND LogP 1-4."""
    mw, logp = _num(mw), _num(logp)
    v = []
    if mw is None or logp is None:
        return _v11("topical", False, ["missing MW/LogP"], "cannot assess", _V11_TOPICAL_SRCS)
    if mw > 500:
        v.append(f"MW {mw:.0f} > 500 (poor stratum-corneum permeation)")
    if logp < 1:
        v.append(f"LogP {logp} < 1 (too polar to partition into skin lipids)")
    if logp > 4:
        v.append(f"LogP {logp} > 4 (too lipophilic — stays in stratum corneum, poor flux)")
    return _v11("topical", not v, v,
                "permeation window MW<=500, LogP~1-3" if v else "within topical permeation window",
                _V11_TOPICAL_SRCS)


def oral_feasible(mw, logp, hbd, hba) -> Feasibility:
    """v11 API, unchanged. Lipinski Ro5, one violation allowed."""
    mw, logp, hbd, hba = _num(mw), _num(logp), _num(hbd), _num(hba)
    v = []
    if None in (mw, logp, hbd, hba):
        return _v11("oral", False, ["missing property"], "cannot assess", _V11_ORAL_SRCS)
    if mw > 500: v.append(f"MW {mw:.0f} > 500")
    if logp > 5: v.append(f"LogP {logp} > 5")
    if hbd > 5: v.append(f"HBD {hbd:.0f} > 5")
    if hba > 10: v.append(f"HBA {hba:.0f} > 10")
    # Lipinski allows one violation
    return _v11("oral", len(v) <= 1, v,
                "Lipinski Ro5" + (" (>=2 violations → poor oral bioavailability)"
                                  if len(v) > 1 else ""),
                _V11_ORAL_SRCS)


def assess(compound: dict, route: str) -> Feasibility:
    """v11 API, unchanged. compound: {name?, mw, logp, hbd, hba}.
    route: 'topical' | 'oral' | 'unknown'."""
    if route == "topical":
        return topical_feasible(compound.get("mw"), compound.get("logp"))
    if route == "oral":
        return oral_feasible(compound.get("mw"), compound.get("logp"),
                             compound.get("hbd"), compound.get("hba"))
    # unknown route: fail if it clears NEITHER window (delivery-implausible by any route)
    t = topical_feasible(compound.get("mw"), compound.get("logp"))
    o = oral_feasible(compound.get("mw"), compound.get("logp"),
                      compound.get("hbd"), compound.get("hba"))
    ok = t.feasible or o.feasible
    return _v11("unknown", ok, (t.violations + o.violations) if not ok else [],
                "delivery-implausible by BOTH topical and oral routes" if not ok
                else "feasible by at least one route",
                _V11_TOPICAL_SRCS + _V11_ORAL_SRCS)


def screen(compounds: list, route: str) -> dict:
    """v11 API, unchanged. compounds: list of dicts with name/mw/logp/hbd/hba.
    Returns {name: Feasibility}."""
    out = {}
    for c in compounds:
        out[c.get("name", "?")] = assess(c, route)
    return out


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    comps = [
        {"name": "Pachymic acid", "mw": 528.8, "logp": 7.2, "hbd": 2, "hba": 5},
        {"name": "Militarine", "mw": 726.7, "logp": -0.5, "hbd": 9, "hba": 17},
        {"name": "Imperatorin", "mw": 270.28, "logp": 3.4, "hbd": 0, "hba": 4},
    ]
    print("=== v11 compatibility layer (frozen behaviour) ===")
    for route in ("topical", "oral"):
        print(f"--- {route} ---")
        for name, f in screen(comps, route).items():
            print(f"  {name:16s} feasible={f.feasible}  {f.violations}")

    print("\n=== v12 three levels ===")
    tac = assess_delivery({"name": "tacrolimus", "mw": 804.0, "logp": 2.7},
                          Route.TOPICAL_SKIN, Modality.SMALL_MOLECULE, "ointment")
    print(f"  tacrolimus ointment   {tac.level.value:16s} {tac.violations}")
    sema = assess_delivery({"name": "semaglutide", "mw": 4114.0}, Route.ORAL, Modality.PEPTIDE,
                           "tablet")
    print(f"  oral semaglutide      {sema.level.value:16s} dds={[d.dds_class for d in sema.dds_candidates][:1]}")
    nov = assess_delivery({"name": "NovelPeptide-1", "mw": 2500.0}, Route.ORAL, Modality.PEPTIDE)
    print(f"  unprecedented peptide {nov.level.value:16s}")
    ana = assess_delivery({"name": "NovelPeptide-1", "mw": 2500.0}, Route.ORAL, Modality.PEPTIDE,
                          precedents=[analogy("another peptide of similar size is absorbed",
                                              Modality.PEPTIDE, Route.ORAL)])
    print(f"  ... with analogy only {ana.level.value:16s} flags={ana.flags}")
    pach = assess_delivery(comps[0], Route.TOPICAL_SKIN)
    print(f"  pachymic acid topical {pach.level.value:16s} {len(pach.dds_candidates)} DDS candidates")
    dupi = assess_delivery({"name": "dupilumab"}, Route.SUBCUTANEOUS, Modality.PROTEIN_ANTIBODY)
    print(f"  dupilumab SC          {dupi.level.value:16s}")
