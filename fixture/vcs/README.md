# vcs — the revision fixture

A real git repo, materialized by the suite at startup with
deterministic commits (fixed author, fixed dates — see
FIXTURES.md). It carries the v1.5 revision surface: two branches
(`main`, `feature`) diverging by one file, one lightweight tag
(`v1.0`), a three-commit file (`HISTORY.md`), and a two-commit
blame-able file (`BLAME.md`).
