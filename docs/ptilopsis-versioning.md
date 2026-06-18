# PtilopsisRadar Versioning

PtilopsisRadar uses its own product version line starting at `0.1.0`.

This version line is intentionally separate from upstream TrendRadar `6.x`.
PtilopsisRadar is a product-boundary fork, so its release numbers describe the
radar product surface rather than upstream feature history.

## Version Lines

- Main product: `MAJOR.MINOR.PATCH`, starting at `0.1.0`.
- MCP Server: displayed as `0.1.0-mcp`.
- Config files: keep their existing schema versions, such as
  `config.yaml Version: 2.3.0`.
- CR schemas, dispatch receipts, scoring profiles, and lifecycle reports keep
  their own internal schema/profile versions.

Version comparison uses the numeric `MAJOR.MINOR.PATCH` portion. A display
suffix such as `-mcp` is preserved in UI/output but ignored for ordering.

## Future Rename Plan

The Python package and CLI command remain `trendradar` for now. A full rename
should be handled as a separate migration:

1. Add `ptilopsis-radar` as a CLI alias while keeping `trendradar`.
2. Publish Docker image aliases for the new product name.
3. Rename MCP-facing names and docs after aliases are in place.
4. Only then consider package/module renames, with compatibility shims.

This keeps the version reset small and avoids breaking existing deployments.
