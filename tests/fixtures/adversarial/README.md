# Adversarial inputs

Hostile archives are **generated at test time** by `tests/archives.py` (never committed):
zip-slip (`../`), absolute paths, symlink members, a zip bomb (compression ratio), too many
entries, and a file with a `.dbc` extension that is not an archive. The reader must refuse
each one with a warning and carry on with the rest of the input.
