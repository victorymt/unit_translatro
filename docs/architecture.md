# Architecture

The project uses a layered, compatibility-first architecture.  Existing root
modules remain supported so scripts and packaged entry points do not need a
flag day migration.

```text
CLI / TUI / HTTP / batch
            |
        application
            |
          domain
            ^
    settings / catalog / files
```

## Boundaries

- `converter_core.py` is the deterministic domain: value objects, validation,
  and conversion calculations. It does not read files or know about Textual,
  HTTP, or command-line flags.
- `unit_translator.application` owns use cases and the public request schema.
  `ConversionService` is the shared entry point for typed requests and request
  mappings.
- `unit_translator.adapters` holds transport presentation concerns. The HTTP
  adapter parses framing and the Textual adapter provides calculator view
  models and compose fragments.
- `app_config.py`, `pricing_catalog.py`, and `settings_store.py` provide
  file-backed settings, price catalogs, and editable-document persistence.
- `unit_converter.py`, `web_api.py`, `tui_app.py`, and `batch_processing.py`
  are composition roots. They select configuration and presentation, then
  delegate conversion work to `ConversionService`.

## Compatibility rules

- Keep existing CLI flags, API paths, JSON fields, error codes, and root-module
  imports working while extracting modules.
- Put new cross-entry-point behaviour in `unit_translator.application`; do not
  duplicate it in CLI, TUI, batch, or HTTP handlers.
- Keep transports responsible only for parsing, rendering, and their own
  lifecycle concerns.
- Add a regression test before moving a public contract, then run the full
  unit suite after each migration step.
