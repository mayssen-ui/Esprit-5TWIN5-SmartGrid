# Résumé du schéma SmartGrid-Semantic

```
Espace de noms (préfixe sg:) : http://www.semanticweb.org/smartgrid-semantic#

CLASSES (hiérarchie) :
  - sg:Building
    - sg:CommercialBuilding
    - sg:IndustrialBuilding
    - sg:RenewableBuilding  [classe définie]
    - sg:ResidentialBuilding
  - sg:Energy
    - sg:NonRenewableEnergy
    - sg:RenewableEnergy
  - sg:EnergySource
    - sg:RenewableEnergySource  [classe définie]
    - sg:SolarSource
    - sg:WindSource
  - sg:EnergyStorage
    - sg:BatteryStorage
  - sg:GridElement
    - sg:GridNode
    - sg:Substation
  - sg:User

PROPRIÉTÉS D'OBJET (domaine -> portée) :
  - sg:connectedTo : GridElement -> GridElement [symétrique]
  - sg:consumes : Building -> Energy
  - sg:contains : Substation -> GridNode
  - sg:feeds : EnergySource -> GridNode
  - sg:hasSource : GridNode -> EnergySource
  - sg:hasStorage : Building -> EnergyStorage
  - sg:locatedIn : Building -> GridNode
  - sg:manages : User -> GridNode
  - sg:owns : User -> Building
  - sg:produces : EnergySource -> Energy
  - sg:storesEnergy : EnergyStorage -> Energy
  - sg:suppliedBy : Building -> EnergySource

PROPRIÉTÉS DE DONNÉES (domaine -> type) :
  - sg:hasCapacity : EnergySource -> xsd:decimal
  - sg:hasConsumption : Building -> xsd:decimal
  - sg:hasEfficiency : EnergyStorage -> xsd:decimal
  - sg:hasEmail : User -> xsd:string
  - sg:hasInstallationDate : GridElement -> xsd:dateTime
  - sg:hasLocation : GridElement -> xsd:string
  - sg:hasName : Thing -> xsd:string
  - sg:hasPowerOutput : EnergySource -> xsd:decimal
  - sg:hasRole : User -> xsd:string
  - sg:hasStorageCapacity : EnergyStorage -> xsd:decimal
  - sg:hasVoltage : GridElement -> xsd:decimal

REMARQUES : les individus sont typés avec leur classe la plus précise ; pour trouver toutes les instances d'une classe, utiliser  ?x a/rdfs:subClassOf* sg:Classe .
```
