"""Libellés français, unités et règles de validation associés aux éléments de l'ontologie.

Les unités sont des indications d'affichage (MW, kV…) : l'ontologie ne les précise pas.
"""
from __future__ import annotations

CLASSES_FR = {
    "EnergySource": ("source d'énergie", "sources d'énergie"),
    "SolarSource": ("source solaire", "sources solaires"),
    "WindSource": ("source éolienne", "sources éoliennes"),
    "EnergyStorage": ("stockage d'énergie", "stockages d'énergie"),
    "BatteryStorage": ("batterie", "batteries"),
    "Building": ("bâtiment", "bâtiments"),
    "ResidentialBuilding": ("bâtiment résidentiel", "bâtiments résidentiels"),
    "CommercialBuilding": ("bâtiment commercial", "bâtiments commerciaux"),
    "IndustrialBuilding": ("bâtiment industriel", "bâtiments industriels"),
    "GridElement": ("élément du réseau", "éléments du réseau"),
    "GridNode": ("nœud du réseau", "nœuds du réseau"),
    "Substation": ("poste électrique", "postes électriques"),
    "Energy": ("énergie", "énergies"),
    "RenewableEnergy": ("énergie renouvelable", "énergies renouvelables"),
    "NonRenewableEnergy": ("énergie non renouvelable", "énergies non renouvelables"),
    "User": ("utilisateur", "utilisateurs"),
    "RenewableEnergySource": ("source d'énergie renouvelable", "sources d'énergie renouvelable"),
    "RenewableBuilding": ("bâtiment alimenté en renouvelable", "bâtiments alimentés en renouvelable"),
}

# nom -> (libellé, unité, borne min incluse ?, borne min, borne max)
PROPS_FR = {
    "hasName": ("Nom", ""),
    "hasCapacity": ("Capacité installée", "MW"),
    "hasPowerOutput": ("Puissance produite", "MW"),
    "hasConsumption": ("Consommation", "MW"),
    "hasStorageCapacity": ("Capacité de stockage", "MWh"),
    "hasEfficiency": ("Efficacité (0 à 1)", ""),
    "hasVoltage": ("Tension", "kV"),
    "hasLocation": ("Localisation", ""),
    "hasInstallationDate": ("Date d'installation", ""),
    "hasEmail": ("Adresse e-mail", ""),
    "hasRole": ("Rôle", ""),
    "produces": ("Produit (énergie)", ""),
    "consumes": ("Consomme (énergie)", ""),
    "storesEnergy": ("Stocke (énergie)", ""),
    "connectedTo": ("Connecté à", ""),
    "suppliedBy": ("Alimenté par (source)", ""),
    "locatedIn": ("Situé sur le nœud", ""),
    "contains": ("Contient (nœuds)", ""),
    "hasStorage": ("Possède la batterie", ""),
    "hasSource": ("Alimenté par les sources", ""),
    "feeds": ("Alimente le nœud", ""),
    "owns": ("Possède (bâtiments)", ""),
    "manages": ("Gère (nœuds)", ""),
}

# Règles de validation : (minimum, minimum_strict, maximum)
REGLES_NUM = {
    "hasCapacity": (0, True, None),
    "hasPowerOutput": (0, False, None),
    "hasConsumption": (0, False, None),
    "hasStorageCapacity": (0, True, None),
    "hasEfficiency": (0, False, 1),
    "hasVoltage": (0, True, None),
}

# Propriétés obligatoires à la création
OBLIGATOIRES = ["hasName"]

ROLES = ["admin", "lecteur"]


def nom_classe(c: str, pluriel: bool = False) -> str:
    fr = CLASSES_FR.get(c)
    return fr[1 if pluriel else 0] if fr else c


def libelle_prop(p: str) -> str:
    return PROPS_FR.get(p, (p, ""))[0]


def unite_prop(p: str) -> str:
    return PROPS_FR.get(p, ("", ""))[1]


def libelle_avec_unite(p: str) -> str:
    u = unite_prop(p)
    return f"{libelle_prop(p)} ({u})" if u else libelle_prop(p)


# Libellés courts avec article, pour les phrases (« la consommation », « l'efficacité »)
LE_PROP = {
    "hasCapacity": "la capacité installée", "hasPowerOutput": "la puissance produite",
    "hasConsumption": "la consommation", "hasStorageCapacity": "la capacité de stockage",
    "hasEfficiency": "l'efficacité", "hasVoltage": "la tension", "hasLocation": "la localisation",
    "hasInstallationDate": "la date d'installation", "hasEmail": "l'adresse e-mail", "hasRole": "le rôle",
    "hasName": "le nom",
}


def le_prop(p: str) -> str:
    return LE_PROP.get(p, "la propriété " + libelle_prop(p).lower())
