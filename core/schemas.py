"""
core/schemas.py — Schémas Pydantic centralisés du SVIA
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    """Représente une source documentaire citée dans une réponse."""
    source: str  = Field(description="Nom de la source")
    titre: str   = Field(description="Titre de l'article")
    url: str     = Field(description="URL de l'article original")
    date: str    = Field(description="Date de publication (YYYY-MM-DD)")
    score: float = Field(description="Score de pertinence entre 0 et 1")


class SuggestionItem(BaseModel):
    """Représente une recommandation actionnable pour le DIIF/BEAC."""
    titre: str = Field(description="Titre court de la recommandation")
    description: str = Field(description="Description détaillée et actionnable")
    priorite: Literal["haute", "moyenne", "faible"] = Field(
        description="Niveau de priorité : haute, moyenne ou faible"
    )
    dimension: str = Field(
        description="Dimension d'inclusion financière concernée"
    )


class SVIAResponse(BaseModel):
    """Réponse structurée complète produite par l'agent SVIA."""
    reponse: str = Field(
        description=(
            "Synthèse factuelle en français, sourcée, 300 à 400 mots. "
            "Cite explicitement les sources utilisées (nom + titre + date)."
        )
    )
    suggestions: list[SuggestionItem] = Field(
        default_factory=list,
        description=(
            "Exactement 2 à 3 recommandations actionnables pour le DIIF/BEAC, "
            "contextualisées pour la zone CEMAC et la SRIF 2025-2029."
        ),
    )
    dimension: str | None = Field(
        default=None,
        description="Dimension d'inclusion financière principale identifiée",
    )
    requete_rag: str = Field(
        default="",
        description="Requête enrichie utilisée pour la recherche sémantique",
    )


@dataclass
class SVIADeps:
    """
    Dépendances injectées dans les outils de l'agent au moment de l'exécution.
    Accumule l'état intermédiaire produit par chaque tool call.
    """
    historique: list
    dimension_hint: str | None = None
    zone_hint: str | None = None
    cible_hint: str | None = None
    top_k: int = 8
    chunks_trouves: list = field(default_factory=list)
    sources_collectees: list = field(default_factory=list)
    requete_rag_utilisee: str = ""
    dimension_detectee: str | None = None
    contexte_formate: str = ""
