# shared-library

Design fixture for [the shared-library migration design](../../docs/shared-library-migration-design.md). Current pipebridge does not convert these files. `@Library` is still `PB-LIB`.

Do not wire this directory into CI or `scripts/validate-python-build-example.py` until an implementation PR exists. There is no `migration/` output and no live workflow here.

`success/` is the representative case: a `vars/publish.groovy` helper runs shell, takes a literal argument, uses one supported `string` credential binding, and stashes files that a later stage restores. The library root is `build-lib/`, not `lib/`, because the repository gitignore ignores every `lib/` directory.

`failure/` converts under that design, then fails at runtime on `exit 1` before `echo restored`.

Neither fixture is a claim that today's `pipebridge convert` accepts them.
