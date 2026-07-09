import json


def test_openrouter_picker_keeps_only_minimax_m3_from_remote_catalog(monkeypatch):
    from hermes_cli import models

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "anthropic/claude-sonnet-5", "supported_parameters": ["tools"]},
                        {"id": "minimax/minimax-m3", "supported_parameters": ["tools"]},
                    ]
                }
            ).encode()

    models._openrouter_catalog_cache = None
    monkeypatch.setattr(
        "hermes_cli.model_catalog.get_curated_openrouter_models",
        lambda: [
            ("anthropic/claude-sonnet-5", ""),
            ("minimax/minimax-m3", "remote desc"),
        ],
    )
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())

    assert models.fetch_openrouter_models(force_refresh=True) == [
        ("minimax/minimax-m3", "recommended")
    ]


def test_model_picker_builtin_provider_allowlist_excludes_provider_zoo(monkeypatch):
    from hermes_cli.models import MODEL_PICKER_PROVIDER_ALLOWLIST, group_providers

    rows = group_providers(["openrouter", "anthropic", "openai-codex", "openai-api"])
    filtered = []
    for row in rows:
        if row["kind"] == "group":
            members = [m for m in row["members"] if m in MODEL_PICKER_PROVIDER_ALLOWLIST]
            if members:
                filtered.append({**row, "members": members})
        elif row["slug"] in MODEL_PICKER_PROVIDER_ALLOWLIST:
            filtered.append(row)

    assert any(row.get("slug") == "openrouter" for row in filtered)
    assert any(row.get("members") == ["openai-codex"] for row in filtered)
    assert all(row.get("slug") != "anthropic" for row in filtered)
    assert all("openai-api" not in row.get("members", []) for row in filtered)
