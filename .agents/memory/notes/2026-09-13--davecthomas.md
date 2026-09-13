# Decision notes 2026-09-13

## 2026-09-13T12:28Z · davecthomas · feat/repo-connections

**Decision:** let a repository declare its own connections, discovered deterministically
**Why:** Part of #61. A decision recorded in one repository often governs code in another, and there was nowhere to say so. Rather than a registry of every repository an organisation owns, each repository declares only its own edges: the record sits next to the repository that has them, travels with a clone, and needs nobody's permission to write. Discovery is deterministic and offline, reading what the repository already states about its dependencies: .gitmodules, git dependency URLs in package.json, pyproject.toml, go.mod, Cargo.toml and requirements files, and same-organisation references in GitHub Actions workflows. Only references on the repository's own git host count, so a public dependency is not mistaken for a team edge, and a published action from another organisation is tooling rather than a relationship. bootstrap-repo rediscovers on every run. An entry added by hand, marked "declared by hand", survives rediscovery, because someone recording a relationship the manifests cannot show must not have it erased.
**Commit:** 31d6ccd
**Source:** commit-capture

