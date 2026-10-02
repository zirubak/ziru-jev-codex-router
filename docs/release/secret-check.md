# Secret check scope

The initial distribution history contains no copied research Git history.
The pre-commit scanner checks staged file content without printing matches.
Three exact, file-bound SHA256 allowlist entries correspond to inspected
upstream synthetic fixture strings, not usable credentials. New values in
those same files remain subject to scanning.

The scanner is not proof against every credential format. Runtime directories,
env files, raw logs and backups are separately excluded. Git hook configuration
is local Git state: clones must run `git config core.hooksPath .githooks` to
activate it; committing the hook alone cannot activate it in another clone.
