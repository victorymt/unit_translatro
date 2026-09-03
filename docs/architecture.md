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
- `unit_translator.adapters.tui.bc_calculator` owns the optional session-level
  `bc -l` PTY calculator, its bounded history, and process lifecycle. It is
  intentionally separate from domain conversion and configuration state.
- `unit_translator.infrastructure` owns catalogs, user configuration, and
  editable settings documents.
- `unit_translator.commands` wires these layers into the installed commands.

## Public contracts

- The stable embedding API is exported from `unit_translator`.
- Run the application from source with `python -m unit_translator` or use the
  installed `unit-translator` command.
- Keep CLI flags, HTTP paths, JSON fields, and adapter error codes backward
  compatible. Add a regression test before changing any of them.

The ncurses workbench keeps a dynamic, bordered calculator panel above the page
footer. The panel renders recent history as two-line REPL entries immediately
above the input; it consumes comparison/detail rows before touching the main
parameters or results. The panel is session-only and does not participate in
settings save/restore or dirty tracking. `bc` is an optional system executable;
unavailable-process and timeout errors are rendered in the panel rather than
preventing the main TUI from starting.
