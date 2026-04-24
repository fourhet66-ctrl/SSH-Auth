# ssh-auth Roadmap

`ssh-auth` is a Codex remote development profile switcher. The roadmap keeps that scope narrow: help Codex keep using the stable `codex-active` SSH host while developers switch the real GPU server or devbox behind it.

## v0.1.x: Reliable Codex profile switching

- Keep `codex-active` stable across profile changes.
- Make `list`, `add`, `switch`, `check`, and `connect` predictable for daily Codex remote development.
- Preserve the current security model: no SSH password storage, no private key storage, and no modification of Codex private databases.
- Improve diagnostics when OpenSSH config includes, aliases, keys, or remote connectivity fail.
- Keep profile data focused on what Codex switching needs: host, user, port, identity file path, proxy jump, tags, active profile, status, and resource summaries.

## Next: Better remote readiness checks

- Expand `ssh-auth check` output for Codex readiness, including clearer SSH auth failures and missing remote prerequisites.
- Improve GPU and memory summaries without turning ssh-auth into a general monitoring tool.
- Add safer redaction guidance for issue reports and troubleshooting output.

## Later: Workflow polish

- Add import/export helpers for moving ssh-auth profile metadata between developer machines.
- Improve shell completion for profile selectors.
- Add documentation for common Codex remote development patterns, including multi-GPU hosts, jump hosts, and temporary cloud devboxes.

## Non-goals

- Do not become a general-purpose SSH manager.
- Do not store passwords or private keys.
- Do not manage arbitrary server fleets outside the Codex remote development profile-switching workflow.
- Do not depend on Codex private internal storage formats.
