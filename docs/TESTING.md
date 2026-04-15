# Testing Strategy

## Dual-layer approach

### Unit tests

| Where | When | Speed | Dependencies |
|---|---|---|---|
| `packages/etsy-core/tests/` | Every PR | < 5s | Pure Python + respx + freezegun |
| `packages/etsy-mcp-shared/tests/` | Every PR | < 5s | Pure Python |
| `apps/etsy/tests/unit/` | Every PR | < 10s | AsyncMock for managers |

Target coverage: **95%** on `etsy-core`, **90%** on `etsy-mcp-shared` and `etsy_mcp`.

### Integration tests

| Where | When | Speed | Dependencies |
|---|---|---|---|
| `apps/etsy/tests/integration/` | Manual / nightly | 2-5 min | Real Etsy API, real OAuth tokens, real shop |

Gated on `ETSY_INTEGRATION_TESTS=1`. Never runs in default CI.

## Test patterns

### 1. respx HTTP mocking

Every `etsy-core` test that touches HTTP stubs specific Etsy endpoints with exact response shapes. No real network.

```python
import httpx
import respx

@pytest.mark.asyncio
async def test_get_retries_on_429_then_succeeds(client, mock_httpx):
    url = f"{DEFAULT_BASE_URL}/users/me/shops"
    mock_httpx.get(url).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "1"}, json={}),
        httpx.Response(200, json={"shop_id": 42}),
    ])
    result = await client.get("/users/me/shops")
    assert result == {"shop_id": 42}
```

### 2. AsyncMock for manager contracts

App-layer tool tests mock managers (not HTTP). Isolates the tool-layer contract from HTTP mechanics.

```python
async def test_shops_get_me_tool(monkeypatch):
    mock_manager = AsyncMock()
    mock_manager.get_me.return_value = {"shop_id": 12345}
    monkeypatch.setattr("etsy_mcp.runtime.get_shop_manager", lambda: mock_manager)
    from etsy_mcp.tools.shops import shops_get_me
    result = await shops_get_me()
    assert result["success"] is True
```

### 3. Deterministic PKCE via monkeypatched secrets

The `deterministic_pkce` fixture in `conftest.py` patches `secrets.token_bytes` to return zero bytes, making PKCE generation reproducible.

### 4. Concurrent refresh serialization test

Two concurrent `auth.refresh()` calls must result in exactly one network call. The second must observe the freshly-rotated token via the file lock.

### 5. Atomic token write test

After `save_tokens()`, no `.tmp` file lingers. Permission bits are `0600`.

### 6. Field symmetry tests

Every list-output field must be accepted by the matching create/update tool — no silent drops.

### 7. Policy gate sweep

Parametrized test hits every category × action combination with the gate on/off.

### 8. Caplog audit verification

Assert that no log line in any test contains a real access_token or refresh_token. Catches secret leaks the F3 layer might miss.

```python
def test_no_secrets_in_logs(caplog):
    ...
    for record in caplog.records:
        assert "real-access-value" not in record.getMessage()
```

### 9. Fetch-merge-put correctness

Manager-level test: partial merge preserves unmentioned fields, not-found returns False, empty update is a no-op.

### 10. UTC rollover for daily counter

Persisted counter file with a prior date must reset to 0 on load.

## Fixtures

Defined in `packages/etsy-core/tests/conftest.py`:

| Fixture | Purpose |
|---|---|
| `temp_config_dir` | Isolated XDG_CONFIG_HOME under tmp_path |
| `mock_httpx` | respx router intercepting all httpx calls |
| `deterministic_pkce` | Monkeypatched `secrets.token_bytes` for reproducible PKCE |
| `fake_tokens` | Non-expired Tokens with safe placeholder values |
| `expired_tokens` | Expired Tokens that trigger refresh |
| `auth_factory` | Builds EtsyAuth pointed at the temp token store |
| `token_endpoint_success` | Default successful token endpoint response body |

## Running

```bash
# Unit only — fast, no network
make test-unit

# Specific package
uv run --package etsy-core pytest packages/etsy-core/tests -v

# Specific file
uv run --package etsy-core pytest packages/etsy-core/tests/test_auth.py -v

# Specific test
uv run --package etsy-core pytest packages/etsy-core/tests/test_auth.py::TestRefresh::test_refresh_rotates_tokens -v

# Integration — gated, needs real tokens
ETSY_INTEGRATION_TESTS=1 make test-integration
```

## Integration test cleanup

Every integration test that creates a resource appends a deletion callable to a session-scoped cleanup registry. Resources carry `[etsy-mcp-test]` in their title prefix so a manual reaping script can clean orphans from crashed runs.

```python
@pytest.fixture(scope="session")
def cleanup_registry():
    callbacks = []
    yield callbacks
    for cb in reversed(callbacks):
        try:
            cb()
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")
```

## CI

GitHub Actions matrix: Python 3.13 × [ubuntu-latest, macos-latest]. Every push to `main`, every PR. Integration tests are NOT run in default CI — they require real OAuth tokens that should never live in CI secrets.
