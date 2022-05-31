import os
import pprint
import subprocess
from functools import wraps
from pathlib import Path

import click

import rutils


def inprojhome(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        config = rutils.load_config()
        curdir = os.getcwd()
        try:
            os.chdir(config["PROJ_HOME"])
            f(*args, **kwargs)
        finally:
            os.chdir(curdir)

    return wrapper


@click.group()
def cli():
    pass


def docker_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        p = run_cmd(["docker", "-v"])
        if p.returncode != 0:
            raise Exception(
                "We need docker for this operation: {}".format(p.stderr.decode("utf8"))
            )
        f(*args, **kwargs)

    return wrapper


@cli.command()
@inprojhome
def mount_secrets():
    """Will install packages for mounting encrypted filesystem (cryfs)"""
    config = get_config()
    t = run_cmd(["cryfs", "--version"])

    if t.returncode != 0:
        print("Going to install packages fuse and cryfs (using sudo)")
        run_cmd(["sudo", "apt-get", "install", "-y", "fuse", "cryfs"])

    source = os.path.join(config["PROJ_HOME"], config.get("SECRETS_SRCDIR", ".secrets"))
    target = os.path.join(config["PROJ_HOME"], config.get("SECRETS_TGTDIR", "secrets"))
    print("Going to mount encrypted folder {} -> {}".format(source, target))
    print("If generated for the first time, REMEMBER YOUR PASSWORD!!!")
    run_cmd(["cryfs", source, target], capture_output=False)


@cli.command()
@inprojhome
def umount_secrets():
    """Unmount the encrypted folder"""
    config = get_config()
    target = os.path.join(config["PROJ_HOME"], config.get("SECRETS_TGTDIR", "secrets"))
    run_cmd(["cryfs-unmount", target], capture_output=False)


@cli.command()
def config():
    """Show config values as loaded"""
    pprint.pprint(get_config())


@cli.command()
@inprojhome
@docker_required
def jupyter_start():
    """Starts a jupyter notebook (inside the project/jupyter)"""
    config = get_config()
    jupyhome = os.path.abspath(config.get("JUPYTER_HOME", "jupyterbook"))
    if not os.path.exists(jupyhome):
        Path(jupyhome).mkdir(parents=True)

    jupyport = config.get("JUPYTER_PORT", 8888)

    # check we have the jupyterbook image ready
    p = run_cmd(["docker", "images", "rprojc.jupyterbook", "--quiet"])
    if len(p.stdout) == 0:
        print("Image rprojc.jupyterbook not available, going to build it first")
        rebuild_image()

    print("Going to run on port={}".format(jupyport))

    cmd = [
        "docker",
        "run",
        "--name",
        "{}.jupyterbook".format(os.path.basename(config["PROJ_HOME"])),
        "-it",
        "--rm",
        "-v",
        "{}:/home/jovyan/workspace".format(jupyhome),
        "-p",
        "{}:8888".format(jupyport),
        "rprojc.jupyterbook:latest",
        "start.sh",
        "jupyter",
        "lab",
        "--no-browser",
        "--NotebookApp.token=''",
        "--NotebookApp.password=''",
    ]
    run_cmd(cmd, capture_output=False)


@cli.command()
@inprojhome
@docker_required
def jupyter_rebuild_image():
    """Rebuilds the rprojc.jupyter image"""
    rebuild_image()


def rebuild_image():
    curhome = os.getcwd()
    rutilshome = os.path.dirname(rutils.__file__)
    try:
        os.chdir(rutilshome)
        cmd = [
            "docker",
            "build",
            ".",
            "--tag",
            "rprojc.jupyterbook",
            "-f",
            "{}/Dockerfile.jupyterbook".format(rutilshome),
        ]
        p = run_cmd(cmd)
        if p.returncode != 0:
            raise Exception("Failed: {}".format(p.stderr))
    finally:
        os.chdir(curhome)


def get_config():
    return rutils.load_config()


def run_cmd(args, **kwargs):
    kwargs["capture_output"] = kwargs.get("capture_output", True)
    print("Executing: {}".format(" ".join(args)))
    return subprocess.run(args, **kwargs)


if __name__ == "__main__":

    # os.chdir("/dvt/workspace/bitwarden")
    # sys.argv.extend(["jupyter-start"])
    cli()
