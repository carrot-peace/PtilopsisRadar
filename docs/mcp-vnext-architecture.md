# MCP vNext architecture

The MCP server keeps its public contract at 24 tools and two resources while
separating protocol registration, application policy, and domain behavior.

## Runtime layers

1. `server.py` builds the FastMCP application and selects stdio or HTTP.
2. `context.py` owns one application's dependencies and releases them when its
   lifespan ends.
3. `features/` contains the public MCP handlers grouped by functional domain.
4. `tools/` implements domain use cases; `services/` owns reusable data,
   parsing, search, cache, and remote-pull operations.
5. `presentation.py` serializes stable payloads and masks untrusted errors.
6. `transport.py` validates HTTP exposure and bearer authentication.
7. `cli.py` owns command-line parsing only.

Feature handlers must stay thin: validate transport-facing arguments, resolve
dependencies from `MCPContext`, delegate once, and serialize the result. New
business rules belong in a role-specific tool or service.

## Functional domains

| Domain | Feature module | Responsibility |
| --- | --- | --- |
| Query | `features/query.py` | news, RSS, date and platform queries |
| Analysis/Search | `features/analysis_search.py` | search and analytics |
| Management | `features/management.py` | health, config and cache views |
| Crawl | `features/crawl.py` | bounded one-off collection |
| Storage | `features/storage.py` | safe remote-to-local synchronization |
| Reader | `features/reader.py` | bounded article extraction |

## Trust boundary

Stdio retains the historical trusted behavior. HTTP binds to loopback and is
read-only by default. Public HTTP requires a bearer token unless the operator
explicitly opts into insecure exposure. Write operations additionally require
`MCP_HTTP_ALLOW_WRITE=true`. HTTP responses mask internal error details.

The process refuses ambiguous or invalid boolean environment values instead of
silently enabling a capability.

## Lifecycle and compatibility rules

- `MCPContext` owns every dependency passed to it. On shutdown it invokes at
  most one of `aclose`, `close`, or `cleanup` per unique dependency.
- Cleanup failures are logged and do not prevent remaining dependencies from
  being released.
- Tool names, resource URIs, descriptions, payload envelopes, and stdio
  behavior are locked by contract tests.
- Input bounds, architecture line budgets, stdio/HTTP protocol smoke tests, and
  source dependency checks must pass before extending a domain.
- Add a new feature module or role-specific service instead of placing another
  handler or business rule in `server.py`.
