import subprocess
from pathlib import Path

import click


@click.group()
def cli():
    pass


@cli.command()
def docs():
    """Will build documentation"""
    subprocess.check_call(["sphinx-build", "docs", ".docs"])


@cli.command()
def install():
    """Install virtualenv and set everything up (for development)"""
    run_pip(["install", "-e", ".[dev]"])
    run_pip(["install", "-e", ".[docs]"])
    run_pip(["install", "-e", "."])


def run_cmd(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def run_pip(args):
    cmd = [".venv/bin/python", "-m", "pip"]
    cmd += args
    run_cmd(cmd)


if __name__ == "__main__":
    cli()
