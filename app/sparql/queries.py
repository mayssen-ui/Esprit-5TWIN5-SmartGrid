"""Catalogue des requêtes croisées (plusieurs classes) avec libellés en langage humain."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RequeteCroisee:
    id: str
    libelle: str          # phrase en français affichée à l'utilisateur
    explication: str      # ce que fait la requête, sans jargon
    sparql: str
    techniques: tuple[str, ...] = ()   # fonctionnalités SPARQL illustrées


CATALOGUE: list[RequeteCroisee] = [
    RequeteCroisee(
        "batiments_sources",
        "Citer les bâtiments et la source d'énergie qui les alimente",
        "Relie chaque bâtiment à sa source (propriété « alimenté par »).",
        """SELECT ?batiment ?nom_batiment ?source ?nom_source
WHERE {
  ?batiment a/rdfs:subClassOf* sg:Building ;
            sg:hasName ?nom_batiment ;
            sg:suppliedBy ?source .
  ?source sg:hasName ?nom_source .
}
ORDER BY ?nom_batiment""",
        ("jointure",),
    ),
    RequeteCroisee(
        "batiments_batteries",
        "Citer les bâtiments qui possèdent une batterie, avec sa capacité de stockage et son efficacité",
        "Relie chaque bâtiment à sa batterie et affiche ses caractéristiques.",
        """SELECT ?nom_batiment ?nom_batterie ?capacite_stockage ?efficacite
WHERE {
  ?batiment a/rdfs:subClassOf* sg:Building ;
            sg:hasName ?nom_batiment ;
            sg:hasStorage ?batterie .
  ?batterie sg:hasName ?nom_batterie ;
            sg:hasStorageCapacity ?capacite_stockage ;
            sg:hasEfficiency ?efficacite .
}
ORDER BY DESC(?capacite_stockage)""",
        ("jointure", "ORDER BY"),
    ),
    RequeteCroisee(
        "utilisateurs_industriels",
        "Citer les utilisateurs qui possèdent des bâtiments industriels",
        "Relie les utilisateurs aux bâtiments industriels qu'ils possèdent.",
        """SELECT ?nom_utilisateur ?email ?nom_usine ?consommation
WHERE {
  ?u a sg:User ;
     sg:hasName ?nom_utilisateur ;
     sg:owns ?usine .
  ?usine a/rdfs:subClassOf* sg:IndustrialBuilding ;
         sg:hasName ?nom_usine .
  OPTIONAL { ?u sg:hasEmail ?email }
  OPTIONAL { ?usine sg:hasConsumption ?consommation }
}
ORDER BY ?nom_utilisateur""",
        ("jointure", "OPTIONAL"),
    ),
    RequeteCroisee(
        "noeuds_sources",
        "Citer les nœuds du réseau et toutes les sources qui les alimentent",
        "Pour chaque nœud, liste toutes les sources reliées (une ligne par source).",
        """SELECT ?nom_noeud ?nom_source ?puissance_produite
WHERE {
  ?noeud a sg:GridNode ;
         sg:hasName ?nom_noeud ;
         sg:hasSource ?source .
  ?source sg:hasName ?nom_source .
  OPTIONAL { ?source sg:hasPowerOutput ?puissance_produite }
}
ORDER BY ?nom_noeud ?nom_source""",
        ("jointure", "OPTIONAL"),
    ),
    RequeteCroisee(
        "postes_noeuds",
        "Citer les postes électriques et les nœuds qu'ils contiennent, avec la tension",
        "Relie chaque poste aux nœuds qu'il contient et compare leurs tensions.",
        """SELECT ?nom_poste ?tension_poste ?nom_noeud ?tension_noeud
WHERE {
  ?poste a sg:Substation ;
         sg:hasName ?nom_poste ;
         sg:contains ?noeud .
  ?noeud sg:hasName ?nom_noeud .
  OPTIONAL { ?poste sg:hasVoltage ?tension_poste }
  OPTIONAL { ?noeud sg:hasVoltage ?tension_noeud }
}
ORDER BY ?nom_poste""",
        ("jointure", "OPTIONAL"),
    ),
    RequeteCroisee(
        "batiments_renouvelables",
        "Citer les bâtiments alimentés par une source d'énergie renouvelable",
        "Équivalent de la classe définie « RenewableBuilding » : bâtiment dont une source produit une énergie renouvelable.",
        """SELECT DISTINCT ?nom_batiment ?nom_source ?type_energie
WHERE {
  ?batiment a/rdfs:subClassOf* sg:Building ;
            sg:hasName ?nom_batiment ;
            sg:suppliedBy ?source .
  ?source sg:hasName ?nom_source ;
          sg:produces ?energie .
  ?energie a/rdfs:subClassOf* sg:RenewableEnergy .
  BIND(IF(EXISTS { ?source a/rdfs:subClassOf* sg:SolarSource }, "solaire",
       IF(EXISTS { ?source a/rdfs:subClassOf* sg:WindSource }, "éolien", "autre renouvelable")) AS ?type_energie)
}
ORDER BY ?nom_batiment""",
        ("jointure", "BIND", "FILTER EXISTS"),
    ),
    RequeteCroisee(
        "conso_superieure_production",
        "Citer les bâtiments dont la consommation dépasse la production de leur source",
        "Compare la consommation de chaque bâtiment à la puissance produite par la source qui l'alimente.",
        """SELECT ?nom_batiment ?consommation ?nom_source ?puissance_produite
WHERE {
  ?batiment a/rdfs:subClassOf* sg:Building ;
            sg:hasName ?nom_batiment ;
            sg:hasConsumption ?consommation ;
            sg:suppliedBy ?source .
  ?source sg:hasName ?nom_source ;
          sg:hasPowerOutput ?puissance_produite .
  FILTER(?consommation > ?puissance_produite)
}
ORDER BY DESC(?consommation)""",
        ("FILTER",),
    ),
    RequeteCroisee(
        "noeuds_connectes",
        "Citer les nœuds connectés entre eux avec leur localisation",
        "La relation « connecté à » est symétrique : chaque liaison est listée une seule fois.",
        """SELECT ?nom_noeud_1 ?lieu_1 ?nom_noeud_2 ?lieu_2
WHERE {
  ?n1 sg:connectedTo ?n2 ;
      sg:hasName ?nom_noeud_1 .
  ?n2 sg:hasName ?nom_noeud_2 .
  OPTIONAL { ?n1 sg:hasLocation ?lieu_1 }
  OPTIONAL { ?n2 sg:hasLocation ?lieu_2 }
  FILTER(STR(?n1) < STR(?n2))
}
ORDER BY ?nom_noeud_1""",
        ("FILTER", "OPTIONAL", "propriété symétrique"),
    ),
    RequeteCroisee(
        "gros_consommateurs",
        "Citer les bâtiments qui consomment plus de 1 MW",
        "Filtre numérique simple sur la consommation.",
        """SELECT ?nom ?consommation
WHERE {
  ?b a/rdfs:subClassOf* sg:Building ; sg:hasName ?nom ; sg:hasConsumption ?consommation .
  FILTER(?consommation > 1)
}
ORDER BY DESC(?consommation)""",
        ("FILTER", "ORDER BY"),
    ),
    RequeteCroisee(
        "batiments_avec_batterie_optionnelle",
        "Citer tous les bâtiments, avec leur batterie s'ils en ont une",
        "Les bâtiments sans batterie restent dans la liste (case vide).",
        """SELECT ?nom_batiment ?nom_batterie
WHERE {
  ?b a/rdfs:subClassOf* sg:Building ; sg:hasName ?nom_batiment .
  OPTIONAL { ?b sg:hasStorage ?bat . ?bat sg:hasName ?nom_batterie }
}
ORDER BY ?nom_batiment""",
        ("OPTIONAL",),
    ),
    RequeteCroisee(
        "sources_solaires_ou_eoliennes",
        "Citer les sources solaires ou éoliennes (une seule liste)",
        "Fusionne deux motifs de recherche avec UNION.",
        """SELECT ?nom ?type ?capacite
WHERE {
  { ?s a/rdfs:subClassOf* sg:SolarSource . BIND("solaire" AS ?type) }
  UNION
  { ?s a/rdfs:subClassOf* sg:WindSource . BIND("éolienne" AS ?type) }
  ?s sg:hasName ?nom .
  OPTIONAL { ?s sg:hasCapacity ?capacite }
}
ORDER BY ?type ?nom""",
        ("UNION", "BIND"),
    ),
    RequeteCroisee(
        "sources_plusieurs_batiments",
        "Citer les sources qui alimentent au moins 2 bâtiments, avec la consommation totale servie",
        "Regroupe les bâtiments par source (GROUP BY) et ne garde que les groupes de 2 ou plus (HAVING).",
        """SELECT ?nom_source (COUNT(?b) AS ?nb_batiments) (SUM(?conso) AS ?consommation_totale)
WHERE {
  ?b a/rdfs:subClassOf* sg:Building ;
     sg:suppliedBy ?s ;
     sg:hasConsumption ?conso .
  ?s sg:hasName ?nom_source .
}
GROUP BY ?nom_source
HAVING (COUNT(?b) >= 2)
ORDER BY DESC(?consommation_totale)""",
        ("GROUP BY", "HAVING", "agrégats"),
    ),
    RequeteCroisee(
        "batiments_au_dessus_moyenne",
        "Citer les bâtiments qui consomment plus que la moyenne de tous les bâtiments",
        "Utilise une sous-requête pour calculer la moyenne, puis compare chaque bâtiment.",
        """SELECT ?nom ?consommation ?moyenne
WHERE {
  ?b a/rdfs:subClassOf* sg:Building ; sg:hasName ?nom ; sg:hasConsumption ?consommation .
  {
    SELECT (AVG(?c) AS ?moyenne)
    WHERE { ?x a/rdfs:subClassOf* sg:Building ; sg:hasConsumption ?c }
  }
  FILTER(?consommation > ?moyenne)
}
ORDER BY DESC(?consommation)""",
        ("sous-requête", "AVG", "FILTER"),
    ),
    RequeteCroisee(
        "noeuds_atteignables",
        "Citer tous les nœuds atteignables en suivant les connexions à partir du nœud de Tunis",
        "Chemin de propriété « connecté à » répété une ou plusieurs fois (connectedTo+).",
        """SELECT DISTINCT ?nom_atteint ?lieu
WHERE {
  sg:GridNode_Tunis_01 sg:connectedTo+ ?atteint .
  ?atteint sg:hasName ?nom_atteint .
  OPTIONAL { ?atteint sg:hasLocation ?lieu }
  FILTER(?atteint != sg:GridNode_Tunis_01)
}
ORDER BY ?nom_atteint""",
        ("property path", "connectedTo+"),
    ),
    RequeteCroisee(
        "batiments_par_type_choisi",
        "Citer les bâtiments industriels et commerciaux (types choisis à l'avance)",
        "VALUES fournit la liste des types voulus.",
        """SELECT ?nom ?type_batiment ?consommation
WHERE {
  VALUES ?type_batiment { sg:IndustrialBuilding sg:CommercialBuilding }
  ?b a ?type_batiment ;
     sg:hasName ?nom .
  OPTIONAL { ?b sg:hasConsumption ?consommation }
}
ORDER BY ?type_batiment ?nom""",
        ("VALUES",),
    ),
    RequeteCroisee(
        "batiments_sans_source",
        "Citer les bâtiments qui ne sont alimentés par aucune source",
        "Recherche l'absence d'un lien avec FILTER NOT EXISTS.",
        """SELECT ?nom_batiment ?consommation
WHERE {
  ?b a/rdfs:subClassOf* sg:Building ; sg:hasName ?nom_batiment .
  OPTIONAL { ?b sg:hasConsumption ?consommation }
  FILTER NOT EXISTS { ?b sg:suppliedBy ?s }
}
ORDER BY ?nom_batiment""",
        ("FILTER NOT EXISTS",),
    ),
    RequeteCroisee(
        "bilan_par_noeud",
        "Donner pour chaque nœud la production des sources et la consommation des bâtiments",
        "Deux sous-requêtes agrégées sont combinées pour obtenir le bilan de chaque nœud.",
        """SELECT ?nom_noeud ?production ?consommation (?production - ?consommation AS ?bilan)
WHERE {
  ?n a sg:GridNode ; sg:hasName ?nom_noeud .
  { SELECT ?n (SUM(?p) AS ?production)
    WHERE { ?n sg:hasSource ?s . ?s sg:hasPowerOutput ?p } GROUP BY ?n }
  { SELECT ?n (SUM(?c) AS ?consommation)
    WHERE { ?b sg:locatedIn ?n ; sg:hasConsumption ?c } GROUP BY ?n }
}
ORDER BY ?nom_noeud""",
        ("sous-requête", "GROUP BY", "SUM"),
    ),
]

PAR_ID = {q.id: q for q in CATALOGUE}
