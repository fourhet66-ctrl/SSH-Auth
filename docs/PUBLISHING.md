# Publishing

This project is prepared for GitHub releases and PyPI distribution, but publishing requires maintainer credentials.

## GitHub repository metadata

Set the repository description to:

```text
Switch Codex SSH devboxes with one stable alias: codex-active.
```

Recommended topics:

```text
codex
openai
ssh
cli
devbox
remote-development
gpu
machine-learning
developer-tools
python
wsl
ssh-config
productivity
```

## GitHub release

Tag:

```text
v0.1.0
```

Title:

```text
ssh-auth v0.1.0
```

Use the release notes from:

```text
docs/release/v0.1.0.md
```

## PyPI

Build and publish after configuring a PyPI API token:

```shell
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine upload dist/*
```

After PyPI publication, users can install with:

```shell
pipx install ssh-auth
```
