# Permissions

etsy-mcp has two independent authorization layers:

1. **Permission Mode** — controls how mutations are handled
2. **Policy Gates** — hard boundaries that disable specific actions entirely

Both layers are checked at call time. **All tools remain visible and discoverable** in the tool index regardless of policy gate state — discoverability and authorization are separate concerns.

## Permission Mode

Set via `ETSY_TOOL_PERMISSION_MODE`:

| Value | Behavior |
|---|---|
| `confirm` (default) | Mutations require preview-then-confirm. First call returns a preview payload; the agent must call again with `confirm=True` to execute. |
| `bypass` | Mutations execute immediately without confirmation. Intended for automation contexts where a human is not in the loop. |

Read-only tools are always allowed regardless of mode.

### Preview-then-confirm shape

First call (default `confirm=False`):

```json
{
  "success": true,
  "requires_confirmation": true,
  "preview": {
    "operation": "update_listing",
    "listing_id": 12345,
    "current": { "title": "Old Title", "price": 9.99 },
    "proposed": { "title": "New Title", "price": 9.99 },
    "changes": ["title"]
  }
}
```

Second call with `confirm=True`:

```json
{
  "success": true,
  "data": { "listing_id": 12345, "title": "New Title", "price": 9.99, ... },
  "rate_limit": { ... }
}
```

## Policy Gates

Policy gates are env-var-driven hard boundaries. They are checked **after** permission mode but **before** the tool body runs.

### Hierarchy

Two-level, most specific wins:

```
ETSY_POLICY_<CATEGORY>_<ACTION>   # Category-scoped (e.g., ETSY_POLICY_LISTINGS_DELETE)
ETSY_POLICY_<ACTION>              # Global default (e.g., ETSY_POLICY_DELETE)
```

### Actions

| Action | Applies to |
|---|---|
| `CREATE` | All `*_create_*` tools |
| `UPDATE` | All `*_update_*` tools |
| `DELETE` | All `*_delete_*` tools |

Read-only tools are not subject to policy gates.

### Values

| Value | Effect |
|---|---|
| Unset | Allowed (default) |
| `true`, `1`, `yes`, `on` | Allowed |
| `false`, `0`, `no`, `off` | **Denied** — the tool returns an error envelope at call time |

### Categories

The full category list lives in `apps/etsy/src/etsy_mcp/categories.py` -> `ETSY_CATEGORY_MAP`. As of v0.1:

| Category | Tool prefix |
|---|---|
| `shops` | `etsy_shops_*` |
| `listings` | `etsy_listings_*` |
| `listing_images` | `etsy_listing_images_*` |
| `listing_videos` | `etsy_listing_videos_*` |
| `listing_inventory` | `etsy_listing_inventory_*` |
| `listing_properties` | `etsy_listing_properties_*` |
| `listing_translations` | `etsy_listing_translations_*` |
| `listing_digital_files` | `etsy_listing_digital_files_*` |
| `receipts` | `etsy_receipts_*` |
| `payments` | `etsy_payments_*` |
| `shipping` | `etsy_shipping_*` |
| `reviews` | `etsy_reviews_*` |
| `taxonomy` | `etsy_seller_taxonomy_*` |
| `users` | `etsy_users_*` |
| `buyer` | `etsy_buyer_*` |

### Examples

**Block all deletes globally:**
```bash
export ETSY_POLICY_DELETE=false
```

**Allow deletes everywhere except listings:**
```bash
export ETSY_POLICY_DELETE=true
export ETSY_POLICY_LISTINGS_DELETE=false
```

**Read-only mode** (block every mutation):
```bash
export ETSY_POLICY_CREATE=false
export ETSY_POLICY_UPDATE=false
export ETSY_POLICY_DELETE=false
```

### Denial message

When a tool is blocked by a policy gate, it returns:

```json
{
  "success": false,
  "error": "Tool 'etsy_listings_delete' is denied by policy gate. Set ETSY_POLICY_LISTINGS_DELETE=true to enable."
}
```

The error message always includes the env var name to flip — the user is told exactly what to do.

## Tool annotations

Every tool also carries MCP `ToolAnnotations` for client-side filtering:

| Hint | Meaning |
|---|---|
| `readOnlyHint=true` | Tool does not modify state |
| `destructiveHint=true` | Tool deletes or overwrites data — extra caution recommended |
| `idempotentHint=true` | Same arguments produce the same result (safe to retry from the client side) |
| `openWorldHint=true` | Etsy API is a public, uncontrolled domain (always true for etsy-mcp) |

These annotations are advisory — they don't change MCP server behavior, but well-behaved clients can use them to color-code or warn before invoking destructive tools.

## Anchor

`packages/etsy-mcp-shared/src/etsy_mcp_shared/policy_gate.py` is the shared implementation. Tests live in `packages/etsy-mcp-shared/tests/test_policy_gate.py`.
