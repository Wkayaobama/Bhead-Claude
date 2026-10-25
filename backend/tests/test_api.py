"""Route-level checks through the FastAPI app with the fake database."""
from __future__ import annotations

import re

from bson import ObjectId

from app.config import settings
from app.quality import FLAG_THRESHOLD, RULES


def test_health_reports_configuration_facts_without_secrets(api):
    client, _db = api
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "degraded"  # no Mongo in tests
    assert body["mongo"] == "not connected"
    assert body["llm"] == {
        "provider": "anthropic",
        "model": settings.ai_model,
        "effort": settings.ai_effort or None,
        "refusal_fallback": settings.ai_refusal_fallback,
        "configured": False,
    }
    assert body["quality"] == {
        "threshold": FLAG_THRESHOLD,
        "rules": len(RULES),
        "bands": ["clean", "review", "flagged"],
    }
    assert "anthropic_api_key" not in res.text
    assert "sk-ant" not in res.text


def test_quality_config_is_served_from_the_registry(api):
    client, _db = api
    res = client.get("/api/monitor/quality-config")
    assert res.status_code == 200
    body = res.json()
    assert body["threshold"] == FLAG_THRESHOLD
    assert [b["key"] for b in body["bands"]] == ["clean", "review", "flagged"]
    assert len(body["rules"]) == len(RULES)


def test_analyze_persists_scores_bands_and_fired_rules(api):
    client, db = api
    db.job_postings.docs.extend(
        [
            {"_id": ObjectId(), "title": "Clean role", "company": "Co",
             "description": "A proper description of the role.", "salary_range": "100k"},
            {"_id": ObjectId(), "title": "<b>Bad</b>", "company": "",
             "description": "x", "salary_range": "lots"},
        ]
    )
    res = client.post("/api/monitor/analyze")
    assert res.status_code == 200
    body = res.json()
    assert body["analyzed"] == 2
    assert body["flagged"] == 1
    assert body["clean"] == 1
    assert body["threshold"] == FLAG_THRESHOLD
    assert body["rules_applied"] == len(RULES)
    clean, bad = db.job_postings.docs
    assert clean["confidence_score"] == 100 and clean["quality_band"] == "clean"
    assert bad["flagged"] is True and bad["quality_band"] == "flagged"
    assert "html_artifacts" in bad["quality_rules_fired"]
    assert "HTML artefacts in title" in bad["quality_flags"]


def test_hallucinations_default_cutoff_follows_the_threshold(api):
    client, db = api
    res = client.get("/api/monitor/hallucinations")
    assert res.status_code == 200
    count_query = next(q for name, q in db.job_postings.calls if name == "count_documents")
    assert {"confidence_score": {"$lte": FLAG_THRESHOLD - 1}} in count_query["$or"]


def test_job_search_is_literal_not_a_regex(api):
    client, db = api
    db.job_postings.docs.append({"_id": ObjectId(), "title": "C++ Developer", "company": "Co"})
    res = client.get("/api/jobs", params={"search": "C++"})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    query = next(q for name, q in db.job_postings.calls if name == "count_documents")
    assert query["$or"][0]["title"]["$regex"] == re.escape("C++")


def test_jobs_stats_lists_the_shared_categories(api):
    client, _db = api
    res = client.get("/api/jobs/stats")
    assert res.status_code == 200
    assert res.json()["available_categories"][0] == "Engineering"
    assert "Other" in res.json()["available_categories"]


def test_secrets_vault_is_disabled_until_a_key_is_configured(api, monkeypatch):
    client, _db = api
    monkeypatch.setattr(settings, "secrets_encryption_key", "")
    res = client.post("/api/secrets", json={"variable_name": "token", "value": "abc"})
    assert res.status_code == 503
    assert "SECRETS_ENCRYPTION_KEY" in res.json()["detail"]
    assert client.get("/api/secrets").status_code == 503


def test_secrets_round_trip_with_a_configured_key(api, monkeypatch):
    client, db = api
    monkeypatch.setattr(settings, "secrets_encryption_key", "a-long-local-passphrase")
    res = client.post("/api/secrets", json={"variable_name": "my token", "value": "s3cret"})
    assert res.status_code == 201
    assert res.json()["variable_name"] == "MY_TOKEN"
    stored = db.secrets.docs[0]
    assert stored["encrypted_value"] != "s3cret"
    assert client.get("/api/secrets/my_token/value").json()["value"] == "s3cret"
    assert client.get("/api/secrets").json()[0]["masked_value"] == "••••••••"


def test_run_apify_requires_a_token_from_body_or_settings(api, monkeypatch):
    client, db = api
    monkeypatch.setattr(settings, "apify_api_key", "")
    target_id = str(ObjectId())
    res = client.post(f"/api/scraper/run-apify/{target_id}", json={})
    assert res.status_code == 400
    assert "APIFY_API_KEY" in res.json()["detail"]
