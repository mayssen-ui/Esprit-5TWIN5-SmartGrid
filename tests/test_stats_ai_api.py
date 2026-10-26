"""Tests des statistiques, des fonctions d'IA, du raisonnement et de l'API REST."""
import shutil

import pytest

from app.ai import anomalies, chatbot, forecast, recommend, simulation
from app.services import io_service, reasoning, stats


# ---------------------------------------------------------------- statistiques
def test_indicateurs(store):
    k = stats.indicateurs(store)
    assert k["Bâtiments"] == 9 and k["Sources d'énergie"] == 6 and k["Utilisateurs"] == 4
    assert k["Production (MW)"] == pytest.approx(212.5) and k["Consommation (MW)"] == pytest.approx(40.045)
    assert k["Part renouvelable (%)"] == pytest.approx(78.8, abs=0.1)


def test_statistiques_sparql(store):
    t = stats.tout_calculer(store)
    n = dict(zip(t["individus_par_classe"]["classe"], t["individus_par_classe"]["nombre"]))
    assert n["Building"] == 9 and n["SolarSource"] == 3 and n["User"] == 4 and n["GridElement"] == 6
    assert set(t["types_batiments"]["nombre"]) == {3}
    s = t["sources_capacite_production"].set_index("source")
    assert s.loc["SolarFarm_Tunis", "taux_utilisation"] == pytest.approx(0.85)
    assert t["stockage"]["capacite_totale"].iloc[0] == pytest.approx(23.0)
    assert len(t["top_consommateurs"]) == 5 and len(t["bilan_par_noeud"]) == 3
    assert t["bilan_global"]["bilan"].iloc[0] == pytest.approx(172.455)


def test_exports_statistiques(store):
    kpi, t = stats.indicateurs(store), stats.tout_calculer(store)
    assert stats.export_pdf(kpi, t).startswith(b"%PDF") and b"Indicateur" in stats.export_csv(kpi, t)


# ---------------------------------------------------------------- IA
def test_recommandations_et_surcharges(store):
    reco = recommend.recommander("House_Sousse_01", store)
    assert reco.iloc[0]["distance_noeuds"] == 0 and reco.iloc[0]["renouvelable"]
    sur = recommend.sources_surchargees(store)
    assert sur.iloc[0]["source"] == "SolarFarm_Ariana" and sur.iloc[0]["statut"] == "Surchargée"
    assert set(recommend.batiments_sans_alimentation(store)["batiment"]) == {"House_Tunis_01", "House_Sousse_01"}


@pytest.mark.parametrize("modele", list(forecast.MODELES))
def test_prevision(store, modele):
    serie = forecast.serie_simulee("SolarFarm_Tunis", store=store)
    r = forecast.prevoir(serie, 24, modele, 50)
    assert len(r["prevision"]) == 24 and r["prevision"]["prevision"].between(0, 50).all()


def test_anomalies(store):
    serie = forecast.serie_simulee("WindFarm_Bizerte", anomalies=True, store=store)
    assert anomalies.detecter_serie(serie)["anomalie"].sum() >= 3
    msgs = [a["message"] for a in anomalies.anomalies_reseau(store)]
    assert any("Usine Ariana 01" in m for m in msgs)


def test_simulation(store):
    r = simulation.simuler({"type": "ajout_batiment", "consommation": 5, "source": "SolarFarm_Tunis"}, store)
    assert r["ecart_bilan"] == pytest.approx(-5.0)
    r = simulation.simuler({"type": "panne_source", "source": "WindFarm_Bizerte"}, store)
    assert r["apres"]["production"] == pytest.approx(r["avant"]["production"] - 55)
    assert store.query("SELECT ?p WHERE { sg:WindFarm_Bizerte sg:hasPowerOutput ?p }").rows[0]["p"] == 55.0  # base intacte


def test_chatbot_cite_ses_sources(store):
    r = chatbot.repondre("Quelle est la consommation de ESPRIT ?", store=store)
    assert "1.2" in r["texte"] and [s["id"] for s in r["sources"]] == ["ESPRIT"]
    r = chatbot.repondre("Parle-moi de la Ferme solaire de Tunis", store=store)
    assert "SolarFarm_Tunis" in [s["id"] for s in r["sources"]]


# ---------------------------------------------------------------- raisonnement et import/export
def test_raisonnement_hermit(store):
    r = reasoning.verifier_coherence(store)
    renouvelables = {t["individu"] for t in r["types_inferes"] if "RenewableBuilding" in t["types_ajoutes"]}
    assert renouvelables == {"ESPRIT", "Building_Ariana_01", "Factory_Ariana_01", "House_Ariana_01",
                             "Mall_Sousse_01", "Factory_Tunis_01"}
    if shutil.which("java"):
        assert r["coherent"] is True and "HermiT" in r["moteur"]


def test_export_import(store):
    for fmt in io_service.FORMATS:
        contenu, mime, ext = io_service.exporter_graphe(fmt, store)
        assert len(contenu) > 1000
    csv_bytes = io_service.exporter_csv("Building", store)
    assert b"hasConsumption" in csv_bytes
    donnees = ("classe;hasName;hasStorageCapacity;hasEfficiency\n"
               "BatteryStorage;Batt A;4;0.9\nBatteryStorage;Batt B;6;0.8\n").encode()
    assert io_service.importer_csv(donnees, None, store)["crees"] == 2
    erreur = ("classe;hasName;hasEfficiency\nBatteryStorage;Batt C;0.9\nBatteryStorage;Batt D;7\n").encode()
    res = io_service.importer_csv(erreur, None, store)
    assert res["crees"] == 0 and res["erreurs"][0]["ligne"] == 3          # tout ou rien : Batt C n'est pas conservé
    assert store.query("ASK { sg:Batt_C ?p ?o }").boolean is False


# ---------------------------------------------------------------- API REST
def test_api_authentification_et_roles(client, admin, lecteur):
    assert client.get("/api/Building").status_code == 401
    assert client.post("/api/auth/login", data={"username": "inconnu@x.tn", "password": "x"}).status_code == 401
    assert client.get("/api/Building", headers=lecteur).json()["total"] == 9
    r = client.post("/api/User", json={"hasName": "Nouveau"}, headers=lecteur)
    assert r.status_code == 403 and "lecture seule" in r.json()["detail"]
    assert client.get("/api/auth/moi", headers=admin).json()["role"] == "admin"


def test_api_crud_complet(client, admin):
    r = client.post("/api/BatteryStorage", json={"hasName": "Batterie API", "hasStorageCapacity": 7, "hasEfficiency": 0.95},
                    headers=admin)
    assert r.status_code == 201 and r.json()["data"]["id"] == "Batterie_API"
    assert client.get("/api/batterystorage/Batterie_API", headers=admin).json()["donnees"]["hasEfficiency"] == 0.95
    assert client.put("/api/BatteryStorage/Batterie_API", json={"hasStorageCapacity": 9}, headers=admin).status_code == 200
    r = client.post("/api/BatteryStorage", json={"hasName": "Bad", "hasEfficiency": 3}, headers=admin)
    assert r.status_code == 422 and "entre 0 et 1" in r.json()["erreurs"][0]
    assert client.delete("/api/SolarSource/SolarFarm_Tunis", headers=admin).status_code == 409
    assert client.delete("/api/SolarSource/SolarFarm_Tunis?cascade=true", headers=admin).status_code == 200
    assert client.delete("/api/BatteryStorage/Batterie_API", headers=admin).status_code == 200
    assert client.get("/api/Inexistante", headers=admin).status_code == 404


def test_api_nl2sparql_stats_et_swagger(client, admin):
    r = client.post("/api/nl2sparql", json={"question": "Combien de sources éoliennes y a-t-il ?"}, headers=admin)
    assert r.status_code == 200 and "SELECT" in r.json()["sparql"] and r.json()["resultat"]["rows"][0]["nombre"] == 2
    r = client.post("/api/nl2sparql", json={"question": "Ajouter une batterie nommée B1 de capacité 3"}, headers=admin)
    assert r.json()["confirmation_requise"] is True
    assert client.get("/api/stats", headers=admin).json()["kpi"]["Bâtiments"] == 9
    assert client.get("/api/requetes/batiments_sources", headers=admin).json()["rows"]
    assert client.post("/api/raisonnement", headers=admin).status_code == 200
    assert client.get("/api/export/turtle", headers=admin).status_code == 200
    assert client.get("/docs").status_code == 200 and "/api/nl2sparql" in client.get("/openapi.json").json()["paths"]


def test_api_operations_complexes(client, admin, lecteur):
    corps = {"classe": "CommercialBuilding", "donnees": {"hasName": "Boutique", "hasConsumption": 0.7},
             "source": "SolarFarm_Tunis", "noeud": "GridNode_Tunis_01"}
    assert client.post("/api/operations/batiment-complet", json=corps, headers=lecteur).status_code == 403
    assert client.post("/api/operations/batiment-complet", json=corps, headers=admin).status_code == 200
    corps["source"] = "Fantome"
    assert client.post("/api/operations/batiment-complet", json={**corps, "donnees": {"hasName": "B2"}}, headers=admin).status_code == 404
