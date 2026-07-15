# discord-scim

A SCIM adapter that provisions users into an application from the members of a
**Discord guild**. It reads guild members and roles from the Discord API and
pushes them into any app that exposes a **SCIM 2.0** provisioning endpoint —
the same interface Okta, Entra ID, and other IdPs use.

- **Users** — every guild member becomes a SCIM `User` (bots excluded by default).
- **Groups** — each Discord role becomes a SCIM `Group`, with members mirrored
  from role assignments.
- **Deprovisioning** — members who leave the guild are deactivated (or deleted).
- **Safe** — every resource is tagged with a guild-scoped `externalId`
  (`<prefix>:<guild_id>:…`), so the adapter only ever touches users and groups it
  created for *this* guild; resources from other sources — or other guilds sharing
  the same app — are never modified. An empty Discord member snapshot refuses to
  run rather than deprovisioning everyone.

```
  Discord guild                discord-scim               your app (SCIM 2.0)
 ┌──────────────┐   REST     ┌──────────────┐   SCIM     ┌──────────────────┐
 │ members      │ ─────────▶ │ map + diff + │ ─────────▶ │ /Users  /Groups  │
 │ roles        │            │ reconcile    │            │                  │
 └──────────────┘            └──────────────┘            └──────────────────┘
```

## How it works

Each sync run is a full reconciliation:

1. Fetch all guild members and roles from Discord.
2. Build the desired set of SCIM users (one per member) and groups (one per role).
3. List the SCIM resources the adapter owns (matched by `externalId` prefix).
4. Create, update, deactivate/delete, and re-group as needed to converge.

Runs are **idempotent** — a second run with no Discord changes makes no API calls
that mutate state.

## Prerequisites

1. **A Discord bot** — create an application at
   <https://discord.com/developers/applications>, add a bot, and copy its token.
2. **Enable the Server Members Intent** for the bot (Bot → Privileged Gateway
   Intents → *Server Members Intent*). Without it, member listing returns empty.
3. **Invite the bot** to your guild with the `guilds.members.read` scope / `View
   Members` permission.
4. **A SCIM 2.0 endpoint** on your target app, plus a bearer token it issued.

> **Note on emails:** bot tokens cannot read member email addresses. If your app
> requires an email, set `EMAIL_DOMAIN` and the adapter synthesizes addresses as
> `<username>@<domain>`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # or: uv pip install -e ".[dev]"

cp .env.example .env           # then fill in your tokens and IDs
```

## Usage

```bash
# Preview the changes without touching the SCIM API
discord-scim --dry-run

# Run a single reconciliation
discord-scim

# Run continuously, syncing every 5 minutes
discord-scim --interval 300
```

Configuration is read from environment variables or `.env`. See
[`.env.example`](.env.example) for every option; the essentials:

| Variable | Required | Description |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | ✅ | Bot token with the Server Members intent. |
| `DISCORD_GUILD_ID` | ✅ | The guild to provision from. |
| `SCIM_BASE_URL` | ✅ | Base URL of the app's SCIM 2.0 API. |
| `SCIM_TOKEN` | ✅ | Bearer token for the SCIM API. |
| `EMAIL_DOMAIN` | | Synthesize `<username>@<domain>` emails. |
| `MANAGE_GROUPS` | | Mirror roles as groups (default `true`). |
| `DEPROVISION_ACTION` | | `deactivate` (default) or `delete`. |
| `INCLUDE_BOTS` | | Provision bot accounts too (default `false`). |
| `ALLOW_EMPTY_GUILD` | | Permit a run when Discord returns zero members (default `false`). |

## Running with Docker

```bash
docker build -t discord-scim .
docker run --rm --env-file .env discord-scim --interval 300
```

## Development

```bash
ruff check src tests     # lint
pytest                   # test suite
```

The reconciliation engine is covered end-to-end against an in-memory SCIM fake
in [`tests/test_sync.py`](tests/test_sync.py): create, idempotent re-run,
deactivate/delete on leave, role-membership changes, and protection of
foreign SCIM resources.

## License

MIT
