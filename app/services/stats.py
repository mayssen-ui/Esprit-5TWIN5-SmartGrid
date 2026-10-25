"""Statistiques du tableau de bord : tout est calculé par des requêtes SPARQL agrégées."""
from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd

from app.sparql.store import BaseStore, get_store

CLASSES_COMPTEES = (
    "EnergySource SolarSource WindSource EnergyStorage BatteryStorage Building ResidentialBuilding "
    "CommercialBuilding IndustrialBuilding GridElement GridNode Substation Energy RenewableEnergy "
    "NonRenewableEnergy User"
)
_VALUES_CLASSES = " ".join(f"sg:{c}" for c in CLASSES_COMPTEES.split())


@dataclass(frozen=True)
class Stat:
    id: str
    libelle: str
    sparql: str


STATS: dict[str, Stat] = {s.id: s for s in [
    Stat("individus_par_classe", "Nombre d'éléments par catégorie", f"""SELECT ?classe (COUNT(DISTINCT ?s) AS ?nombre)
WHERE {{
  VALUES ?classe {{ {_VALUES_CLASSES} }}
  OPTIONAL {{ ?s a owl:NamedIndividual ; a/rdfs:subClassOf* ?classe }}
}}
GROUP BY ?classe
ORDER BY DESC(?nombre)"""),
    Stat("types_batiments", "Répartition des types de bâtiments", """SELECT ?type (COUNT(?b) AS ?nombre)
WHERE {
  VALUES ?type { sg:ResidentialBuilding sg:CommercialBuilding sg:IndustrialBuilding }
  ?b a ?type .
}
GROUP BY ?type"""),
    Stat("sources_capacite_production", "Capacité installée, production réelle et taux d'utilisation par source", """SELECT ?source ?nom ?capacite ?production (?production / ?capacite AS ?taux_utilisation)
WHERE {
  ?source a/rdfs:subClassOf* sg:EnergySource ;
          sg:hasName ?nom ;
          sg:hasCapacity ?capacite ;
          sg:hasPowerOutput ?production .
}
ORDER BY DESC(?taux_utilisation)"""),
    Stat("renouvelable_vs_non", "Part d'énergie renouvelable et non renouvelable (production)", """SELECT ?categorie (SUM(?p) AS ?production)
WHERE {
  VALUES (?genre ?categorie) { (sg:RenewableEnergy "Renouvelable") (sg:NonRenewableEnergy "Non renouvelable") }
  ?s a/rdfs:subClassOf* sg:EnergySource ;
     sg:produces ?e ;
     sg:hasPowerOutput ?p .
  ?e a/rdfs:subClassOf* ?genre .
}
GROUP BY ?categorie"""),
    Stat("consommation_par_type", "Consommation par type de bâtiment", """SELECT ?type (SUM(?c) AS ?consommation) (COUNT(?b) AS ?nombre)
WHERE {
  VALUES ?type { sg:ResidentialBuilding sg:CommercialBuilding sg:IndustrialBuilding }
  ?b a ?type ; sg:hasConsumption ?c .
}
GROUP BY ?type
ORDER BY DESC(?consommation)"""),
    Stat("top_consommateurs", "Les 5 plus gros consommateurs", """SELECT ?nom ?type ?consommation
WHERE {
  VALUES ?type { sg:ResidentialBuilding sg:CommercialBuilding sg:IndustrialBuilding }
  ?b a ?type ; sg:hasName ?nom ; sg:hasConsumption ?consommation .
}
ORDER BY DESC(?consommation)
LIMIT 5"""),
    Stat("bilan_global", "Bilan production / consommation global", """SELECT ?production ?consommation (?production - ?consommation AS ?bilan)
WHERE {
  { SELECT (SUM(?p) AS ?production) WHERE { ?s a/rdfs:subClassOf* sg:EnergySource ; sg:hasPowerOutput ?p } }
  { SELECT (SUM(?c) AS ?consommation) WHERE { ?b a/rdfs:subClassOf* sg:Building ; sg:hasConsumption ?c } }
}"""),
    Stat("bilan_par_noeud", "Bilan production / consommation par nœud", """SELECT ?noeud ?nom (COALESCE(?prod, 0) AS ?production) (COALESCE(?conso, 0) AS ?consommation)
       (COALESCE(?prod, 0) - COALESCE(?conso, 0) AS ?bilan)
WHERE {
  ?noeud a sg:GridNode ; sg:hasName ?nom .
  OPTIONAL { SELECT ?noeud (SUM(?p) AS ?prod) WHERE { ?noeud sg:hasSource ?s . ?s sg:hasPowerOutput ?p } GROUP BY ?noeud }
  OPTIONAL { SELECT ?noeud (SUM(?c) AS ?conso) WHERE { ?b sg:locatedIn ?noeud ; sg:hasConsumption ?c } GROUP BY ?noeud }
}
ORDER BY ?nom"""),
    Stat("stockage", "Efficacité moyenne et capacité totale des stockages", """SELECT (AVG(?eff) AS ?efficacite_moyenne) (SUM(?cap) AS ?capacite_totale) (COUNT(?s) AS ?nombre)
WHERE {
  ?s a/rdfs:subClassOf* sg:EnergyStorage ;
     sg:hasEfficiency ?eff ;
     sg:hasStorageCapacity ?cap .
}"""),
    Stat("noeuds_par_localisation", "Répartition des nœuds par localisation", """SELECT ?localisation (COUNT(?n) AS ?nombre)
WHERE { ?n a sg:GridNode ; sg:hasLocation ?localisation }
GROUP BY ?localisation
ORDER BY DESC(?nombre)"""),
    Stat("noeuds_par_tension", "Répartition des nœuds par niveau de tension", """SELECT ?tension (COUNT(?n) AS ?nombre)
WHERE { ?n a sg:GridNode ; sg:hasVoltage ?tension }
GROUP BY ?tension
ORDER BY ?tension"""),
    Stat("kpi", "Indicateurs clés", """SELECT ?nb_elements ?nb_batiments ?nb_sources ?nb_noeuds ?nb_utilisateurs ?capacite_totale
WHERE {
  { SELECT (COUNT(DISTINCT ?x) AS ?nb_elements) WHERE { ?x a owl:NamedIndividual } }
  { SELECT (COUNT(DISTINCT ?b) AS ?nb_batiments) WHERE { ?b a/rdfs:subClassOf* sg:Building ; a owl:NamedIndividual } }
  { SELECT (COUNT(DISTINCT ?s) AS ?nb_sources) WHERE { ?s a/rdfs:subClassOf* sg:EnergySource ; a owl:NamedIndividual } }
  { SELECT (COUNT(DISTINCT ?n) AS ?nb_noeuds) WHERE { ?n a sg:GridNode } }
  { SELECT (COUNT(DISTINCT ?u) AS ?nb_utilisateurs) WHERE { ?u a sg:User } }
  { SELECT (SUM(?c) AS ?capacite_totale) WHERE { ?s a/rdfs:subClassOf* sg:EnergySource ; sg:hasCapacity ?c } }
}"""),
]}


def executer(stat_id: str, store: BaseStore | None = None) -> pd.DataFrame:
    """Exécute une statistique et retourne le résultat sous forme de tableau."""
    store = store or get_store()
    res = store.query(STATS[stat_id].sparql)
    return pd.DataFrame(res.rows, columns=res.vars)


def indicateurs(store: BaseStore | None = None) -> dict:
    """Cartes de métriques (KPI) affichées en haut du tableau de bord."""
    store = store or get_store()
    k = executer("kpi", store).iloc[0].to_dict() if len(executer("kpi", store)) else {}
    b = executer("bilan_global", store)
    prod = float(b["production"].iloc[0] or 0) if len(b) else 0.0
    conso = float(b["consommation"].iloc[0] or 0) if len(b) else 0.0
    ren = executer("renouvelable_vs_non", store)
    total_ren = float(ren["production"].sum()) if len(ren) else 0.0
    part_ren = float(ren.loc[ren["categorie"] == "Renouvelable", "production"].sum()) if len(ren) else 0.0
    capacite = float(k.get("capacite_totale") or 0)
    return {
        "Éléments dans le réseau": int(k.get("nb_elements") or 0),
        "Bâtiments": int(k.get("nb_batiments") or 0),
        "Sources d'énergie": int(k.get("nb_sources") or 0),
        "Nœuds du réseau": int(k.get("nb_noeuds") or 0),
        "Utilisateurs": int(k.get("nb_utilisateurs") or 0),
        "Capacité installée (MW)": round(capacite, 2),
        "Production (MW)": round(prod, 2),
        "Consommation (MW)": round(conso, 3),
        "Bilan (MW)": round(prod - conso, 2),
        "Taux d'utilisation (%)": round(100 * prod / capacite, 1) if capacite else 0.0,
        "Part renouvelable (%)": round(100 * part_ren / total_ren, 1) if total_ren else 0.0,
    }


def tout_calculer(store: BaseStore | None = None) -> dict[str, pd.DataFrame]:
    """Toutes les statistiques (hors KPI), prêtes pour les graphiques et les exports."""
    store = store or get_store()
    return {sid: executer(sid, store) for sid in STATS if sid != "kpi"}


def export_csv(kpi: dict, tableaux: dict[str, pd.DataFrame]) -> bytes:
    """Un seul fichier CSV (séparateur « ; », UTF-8 avec BOM pour Excel) regroupant tout."""
    tampon = io.StringIO()
    tampon.write("Indicateurs clés\nIndicateur;Valeur\n")
    for k, v in kpi.items():
        tampon.write(f"{k};{v}\n")
    for sid, df in tableaux.items():
        tampon.write(f"\n{STATS[sid].libelle}\n")
        df.to_csv(tampon, sep=";", index=False)
    return ("﻿" + tampon.getvalue()).encode("utf-8")


def export_pdf(kpi: dict, tableaux: dict[str, pd.DataFrame]) -> bytes:
    """Rapport PDF : indicateurs clés puis un tableau par statistique."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    tampon = io.BytesIO()
    doc = SimpleDocTemplate(tampon, pagesize=A4, title="Rapport SmartGrid")
    el = [Paragraph("Rapport SmartGrid - Statistiques du réseau", styles["Title"]), Spacer(1, 12)]

    def tableau(lignes: list[list], largeurs=None):
        t = Table(lignes, colWidths=largeurs, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6f5c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f5f3")]),
        ]))
        return t

    el.append(Paragraph("Indicateurs clés", styles["Heading2"]))
    el.append(tableau([["Indicateur", "Valeur"]] + [[k, str(v)] for k, v in kpi.items()]))
    for sid, df in tableaux.items():
        el += [Spacer(1, 14), Paragraph(STATS[sid].libelle, styles["Heading3"])]
        if df.empty:
            el.append(Paragraph("Aucune donnée.", styles["Normal"]))
            continue
        def fmt(v):
            return f"{v:.3f}" if isinstance(v, float) else str(v)
        el.append(tableau([list(df.columns)] + [[fmt(v) for v in row] for row in df.values.tolist()]))
    doc.build(el)
    return tampon.getvalue()
