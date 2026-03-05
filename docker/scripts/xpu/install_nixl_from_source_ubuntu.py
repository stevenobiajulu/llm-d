# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright contributors to the vLLM project
# install_prerequisites.py
import argparse
import glob
import json
import os
import subprocess
import sys
import urllib.request

# --- Configuration ---
WHEELS_CACHE_HOME = os.environ.get("WHEELS_CACHE_HOME", "/tmp/wheels_cache")
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
UCX_DIR = os.path.join("/tmp", "ucx_source")
NIXL_DIR = os.path.join("/tmp", "nixl_source")
UCX_INSTALL_DIR = os.path.join("/tmp", "ucx_install")
UCX_REPO_URL = "https://github.com/openucx/ucx.git"
NIXL_REPO_URL = "https://github.com/ai-dynamo/nixl.git"


# --- Helper Functions ---
def get_latest_nixl_version():
    """Helper function to get latest release version of NIXL"""
    try:
        nixl_release_url = "https://api.github.com/repos/ai-dynamo/nixl/releases/latest"
        with urllib.request.urlopen(nixl_release_url) as response:
            data = json.load(response)
            return data.get("tag_name", "0.7.0")
    except Exception:
        return "0.7.0"


NIXL_VERSION = os.environ.get("NIXL_VERSION", get_latest_nixl_version())


def run_command(command, cwd=".", env=None):
    """Helper function to run a shell command and check for errors."""
    print(f"--> Running command: {' '.join(command)} in '{cwd}'", flush=True)
    subprocess.check_call(command, cwd=cwd, env=env)


def is_pip_package_installed(package_name):
    """Checks if a package is installed via pip without raising an exception."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", package_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def get_pip_package_version(package_name):
    """Returns installed package version, or None if not installed."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", package_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        if line.startswith("Version:"):
            return line.split(":", 1)[1].strip()
    return None


def find_nixl_wheel_in_cache(cache_dir):
    """Finds a nixl wheel file in the specified cache directory."""
    # The repaired wheel will have a 'manylinux' tag, but this glob still works.
    search_pattern = os.path.join(cache_dir, f"nixl*{NIXL_VERSION}*.whl")
    wheels = glob.glob(search_pattern)
    if wheels:
        # Sort to get the most recent/highest version if multiple exist
        wheels.sort()
        return wheels[-1]
    return None


def install_system_dependencies():
    """Installs required system packages using apt-get if run as root."""
    if os.environ.get("SKIP_SYSTEM_DEPS", "0") == "1":
        print("--- SKIP_SYSTEM_DEPS=1, skipping system dependency installation. ---", flush=True)
        return

    if os.geteuid() != 0:
        print("\n---", flush=True)
        print(
            "WARNING: Not running as root. \
            Skipping system dependency installation.",
            flush=True,
        )
        print(
            "Please ensure the listed packages are installed on your system:",
            flush=True,
        )
        print(
            "  patchelf build-essential git ninja-build \
            autotools-dev automake libtool libtool-bin pkg-config",
            flush=True,
        )
        print("---\n", flush=True)
        return

    print("--- Running as root. Installing system dependencies... ---", flush=True)
    apt_packages = [
        "patchelf",
        "build-essential",
        "git",
        "ninja-build",
        "autotools-dev",
        "automake",
        "libtool",
        "libtool-bin",
        "pkg-config",
    ]
    run_command(["apt-get", "update"])
    run_command(["apt-get", "install", "-y"] + apt_packages)
    print("--- System dependencies installed successfully. ---\n", flush=True)


def build_and_install_prerequisites(args):
    """Builds UCX and NIXL from source."""

    if not args.force_reinstall and is_pip_package_installed("nixl"):
        print("--> NIXL is already installed. Nothing to do.", flush=True)
        return

    cached_wheel = find_nixl_wheel_in_cache(WHEELS_CACHE_HOME)
    if not args.force_reinstall and cached_wheel:
        print(
            f"\n--> Found self-contained wheel: \
            {os.path.basename(cached_wheel)}.",
            flush=True,
        )
        print("--> Installing from cache, skipping all source builds.", flush=True)
        install_command = [sys.executable, "-m", "pip", "install", cached_wheel]
        run_command(install_command)
        print("\n--- Installation from cache complete. ---", flush=True)
        return

    print(
        "\n--> No installed package or cached wheel found. \
            Starting full build process...",
        flush=True,
    )
    install_system_dependencies()
    ucx_install_path = os.path.abspath(UCX_INSTALL_DIR)

    print("\n[1/2] Configuring and building UCX from source...", flush=True)
    ucx_version = os.environ.get("UCX_VERSION", "master")
    build_env = os.environ.copy()
    build_env["PKG_CONFIG_PATH"] = (
        f"{ucx_install_path}/lib/pkgconfig:{build_env.get('PKG_CONFIG_PATH', '')}".strip(":")
    )
    build_env["LD_LIBRARY_PATH"] = (
        f"{ucx_install_path}/lib:{build_env.get('LD_LIBRARY_PATH', '')}".strip(":")
    )

    run_command(["git", "clone", UCX_REPO_URL, UCX_DIR])
    run_command(["git", "checkout", ucx_version], cwd=UCX_DIR)
    run_command(["./autogen.sh"], cwd=UCX_DIR)
    run_command(
        [
            "./configure",
            f"--prefix={ucx_install_path}",
            "--with-ze=yes",
            "--enable-examples",
            "--enable-mt",
        ],
        cwd=UCX_DIR,
        env=build_env,
    )
    run_command(
        ["make", "CFLAGS=-Wno-error=incompatible-pointer-types", "-j8"],
        cwd=UCX_DIR,
        env=build_env,
    )
    run_command(["make", "install"], cwd=UCX_DIR, env=build_env)
    print("--- UCX build and install complete ---", flush=True)

    print("\n[2/2] Building and installing NIXL from source...", flush=True)
    run_command(["git", "clone", NIXL_REPO_URL, NIXL_DIR])
    run_command(["git", "checkout", NIXL_VERSION], cwd=NIXL_DIR)

    run_command(
        [sys.executable, "-m", "pip", "install", "--upgrade", "meson", "pybind11", "patchelf"],
        env=build_env,
    )
    run_command(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=NIXL_DIR,
        env=build_env,
    )
    run_command(
        [sys.executable, "-m", "pip", "install", "--no-deps", "."],
        cwd=NIXL_DIR,
        env=build_env,
    )

    # Enforce meta package version to match NIXL_VERSION without overriding
    # the locally built nixl-cu12 package.
    meta_version = get_pip_package_version("nixl")
    if meta_version != NIXL_VERSION:
        run_command(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                f"nixl=={NIXL_VERSION}",
            ],
            env=build_env,
        )

    run_command(["rm", "-rf", UCX_DIR, NIXL_DIR])
    print("--- NIXL installation complete ---", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build and install UCX and NIXL dependencies."
    )
    parser.add_argument(
        "--force-reinstall",
        action="store_true",
        help="Force rebuild and reinstall of UCX and NIXL \
        even if they are already installed.",
    )
    args = parser.parse_args()
    build_and_install_prerequisites(args)
