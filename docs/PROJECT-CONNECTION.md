# Project connection with `.suites`

An independent project can opt into the Suites control plane by placing a UTF-8 JSON file named
`.suites` in its project root, then explicitly connecting its absolute path. Connection adds a
catalog-only record to the Suites project ledger; it does not enroll the project in a release suite
or transfer ownership of its lifecycle.

```json
{
  "schema_version": "1.0.0",
  "project_id": "example-project",
  "capabilities": []
}
```

The descriptor schema is [`schemas/project-connection.schema.json`](schemas/project-connection.schema.json).
`project_id` is the project's stable self-declared identity. `capabilities` is a distinct list of
lowercase identifiers the project declares it can offer. The current reader reports these names;
it does not execute project code, call an endpoint, or treat a declaration as verified behavior or
approval. Unknown additive fields are ignored by version 1 readers.

Connect and inspect it with:

```sh
./s connect /absolute/path/to/project
./s project PROJECT --json
```

The connect command only reads the project's `.suites` file and records its path and SHA-256 in the
Suites catalog. It does not write to the project, run project code, verify capability behavior, or
enroll a suite. Repeating the command for the same identity and path is safe. A conflicting
identity or path is refused for operator review.

The project projection is also available with `./s projects --json` and in the web catalog detail
under **Project connection**. The same `project_connection` object is included in `GET /api/catalog`
and `GET /api/catalog/project?name=PROJECT` for local control-plane clients. Declared capabilities
remain labeled unverified.

Suites reports one of these local read states in the project view:

- `not_connected`: no `.suites` file exists.
- `declared`: the file is readable and valid. This confirms the descriptor only; `runtime_verified`
  remains false.
- `invalid`: the file is malformed, unsafe to follow, or outside the supported schema.
- `unavailable`: the project directory cannot be opened safely.

The descriptor is read-only. Adding or updating it changes the live declaration projection, but does
not change operator return points, suite membership, release evidence, or approval. Only the explicit
`connect` command adds a catalog-only row; it does not assign a release suite or change lifecycle
ownership.
