# Architecture

All runtime code and bundled assets live under the `unit_translator` package.
The repository root is reserved for project metadata, documentation, and tool
configuration.

```text
unit_translator/
├── domain/          deterministic models, validation, and calculations
├── application/     use cases and request mapping
├── adapters/        batch, HTTP, serialization, web, and TUI boundaries
├── infrastructure/  file-backed settings and price catalogs
├── commands/        executable CLI composition roots
└── resources/       bundled catalog and browser assets
```

## Dependency direction

```text
commands ─┬─> adapters ─> application ─> domain
          └─> infrastructure ──────────> domain
```

- `unit_translator.domain.conversion` has no terminal, HTTP, or file-system
  dependencies.
- `unit_translator.application.ConversionService` is the shared use-case entry
  point for typed requests and mappings.
- `unit_translator.adapters` owns transport parsing, rendering, and lifecycle
  concerns. Adapters do not duplicate conversion rules.
- `unit_translator.infrastructure` owns catalogs, user configuration, and
  editable settings documents.
- `unit_translator.commands` wires these layers into the installed commands.

## Public contracts

- The stable embedding API is exported from `unit_translator`.
- Run the application from source with `python -m unit_translator` or use the
  installed `unit-translator` command.
- Keep CLI flags, HTTP paths, JSON fields, and adapter error codes backward
  compatible. Add a regression test before changing any of them.
