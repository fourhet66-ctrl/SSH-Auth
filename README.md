# ssh-auth

[English](README.md) | [中文](README.zh-CN.md)

Switch between SSH devboxes for Codex with one stable alias: `codex-active`.

![ssh-auth preview](new.png)

`ssh-auth` is a small CLI for managing SSH connections in a Codex workflow. The preview above was AI-anonymized from an actual usage screenshot.

## Quickstart

Install the command globally from this repo:

```shell
git clone https://github.com/fourhet66-ctrl/SSH-Auth.git ~/SSH-Auth
cd ~/SSH-Auth
./install.sh
```

If your shell cannot find it immediately:

```shell
source ~/.bashrc
```

Initialize SSH config support:

```shell
ssh-auth init
```

Add a server by pasting the SSH command you already use:

```shell
ssh-auth add gpu01 --login "ssh ubuntu@1.2.3.4 -p 22" --setup-key
```

List, switch, and check:

```shell
ssh-auth list
ssh-auth switch 01
ssh-auth check
```

Enable Codex remote support:

```shell
ssh-auth config remote enable
```

In Codex, use this SSH host:

```text
codex-active
```

After that, changing servers is just:

```shell
ssh-auth switch 02
```

## What You Get

```text
     PROFILE     HOST                           STATUS  LAST CHECK  RESOURCES
-----------------------------------------------------------------------------
* 01 gpu01-4090  root@example.com:10317         OK      2m ago      GPU RTX 4090 24.0GB; RAM 125.8GB
  02 gpu02-A800  root@gpu.example.com:10116     OK      5m ago      GPU A800 80.0GB; RAM 251.6GB
```

- `*` marks the active profile.
- `codex-active` always points to the active profile.
- `check` updates connection status and resource info.
- Passwords are never stored by `ssh-auth`.

## Daily Use

Add a server interactively:

```shell
ssh-auth add gpu01
```

Add from a login command:

```shell
ssh-auth add gpu01 --login "ssh ubuntu@1.2.3.4 -p 22"
```

Set up passwordless login while adding:

```shell
ssh-auth add gpu01 --login "ssh ubuntu@1.2.3.4 -p 22" --setup-key
```

If the key does not exist yet, either create it first:

```shell
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519
```

or explicitly let `ssh-auth` run `ssh-keygen`:

```shell
ssh-auth add gpu01 --login "ssh ubuntu@1.2.3.4 -p 22" --setup-key --generate-key
```

List profiles:

```shell
ssh-auth list
```

Switch by number or name:

```shell
ssh-auth switch 01
ssh-auth switch gpu01
```

Check connectivity:

```shell
ssh-auth check          # active profile
ssh-auth check 02       # one profile
ssh-auth check --all    # every profile
```

If you forget the name:

```shell
ssh-auth check list
ssh-auth check 02
```

Open SSH directly:

```shell
ssh-auth connect 01
```

Remove a profile:

```shell
ssh-auth remove 01
```

## How It Works

`ssh-auth` does not modify Codex App private databases.

It manages standard OpenSSH config:

- Registry: `~/.codex/ssh-auth/registry.json`
- Profile snapshots: `~/.codex/ssh-auth/profiles/*.json`
- Managed SSH config: `~/.ssh/config.d/codex-ssh-auth.config`
- Include line in `~/.ssh/config`: `Include ~/.ssh/config.d/*.config`

When you run:

```shell
ssh-auth switch gpu01
```

`ssh-auth` marks `gpu01` active and rewrites:

```sshconfig
Host codex-active
  HostName 1.2.3.4
  User ubuntu
  Port 22
```

So Codex can keep using `codex-active`, while you switch the real target.

## Security

- SSH passwords are never stored.
- `--setup-key` delegates password entry to OpenSSH / `ssh-copy-id`.
- Do not pass passwords on the command line.
- Missing keys are not generated unless you pass `--generate-key`.
- Registry files may contain hostnames, usernames, ports, key paths, check timestamps, and resource summaries. Do not commit your real `~/.codex/ssh-auth` directory.
- Generated profile and registry files use private permissions where supported.

## Development

Run from the repo without installing:

```shell
./ssh-auth --help
python3 -m ssh_auth --help
```

Run tests:

```shell
python3 -m unittest discover -q
python3 -m compileall ssh_auth tests
```

For isolated tests:

```shell
SSH_AUTH_HOME=/tmp/ssh-auth-state \
SSH_AUTH_SSH_DIR=/tmp/ssh-auth-ssh \
CODEX_HOME=/tmp/codex-home \
./ssh-auth list
```

## Acknowledgements

`ssh-auth` was inspired by [`codex-auth`](https://github.com/loongphy/codex-auth), especially its simple account-switching workflow and terminal-first interface.
