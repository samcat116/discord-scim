"""Command line entrypoint for the Discord -> SCIM adapter."""

from __future__ import annotations

import logging
import time

import click

from .config import Settings
from .discord_client import DiscordClient
from .scim_client import ScimClient
from .sync import EmptyGuildSnapshot, SyncEngine


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _run_once(settings: Settings, dry_run: bool) -> None:
    with DiscordClient(settings.discord_bot_token, settings.request_timeout) as discord, ScimClient(
        settings.scim_base_url_normalized, settings.scim_token, settings.request_timeout
    ) as scim:
        engine = SyncEngine(discord, scim, settings)
        report = engine.run(dry_run=dry_run)
    click.echo(("DRY RUN " if dry_run else "") + report.summary())


@click.command()
@click.option(
    "--dry-run", is_flag=True, help="Show what would change without calling the SCIM API."
)
@click.option(
    "--interval",
    type=int,
    default=None,
    help="Run continuously, syncing every N seconds instead of once.",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def main(dry_run: bool, interval: int | None, verbose: bool) -> None:
    """Provision users and groups into a SCIM app from a Discord guild."""
    _configure_logging(verbose)
    settings = Settings()  # type: ignore[call-arg]  # loaded from env / .env

    if interval is None:
        try:
            _run_once(settings, dry_run)
        except EmptyGuildSnapshot as exc:
            raise click.ClickException(str(exc)) from exc
        return

    click.echo(f"Starting continuous sync every {interval}s (Ctrl-C to stop)")
    while True:
        try:
            _run_once(settings, dry_run)
        except Exception:  # noqa: BLE001 - keep the daemon alive across transient failures
            logging.getLogger(__name__).exception("Sync run failed; will retry next interval")
        time.sleep(interval)


if __name__ == "__main__":
    main()
