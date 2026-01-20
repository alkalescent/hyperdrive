"""Legacy setup.py for backward compatibility with pip install."""

import os

import requests
from dotenv import find_dotenv, load_dotenv
from setuptools import find_packages, setup

load_dotenv(find_dotenv("config.env"))


def get_version() -> str:
    """Fetch the latest version tag from GitHub releases API.

    Returns:
        Version string without the 'v' prefix.

    Raises:
        Exception: If the API request fails.
    """
    url = "https://api.github.com/repos/suchak1/hyperdrive/releases/latest"
    token = os.environ.get("GITHUB")
    headers = {"Authorization": f"token {token}"}
    response = requests.get(url, headers=headers if token else None)
    if response.ok:
        data = response.json()
        version = data["tag_name"].replace("v", "")
        return version
    else:
        raise Exception(response.text)


def get_requirements() -> list[str]:
    """Read dependencies from requirements.txt.

    Returns:
        List of requirement strings.
    """
    with open("requirements.txt") as file:
        return [line.strip() for line in file if line]


def get_readme() -> str:
    """Read the README.md file contents.

    Returns:
        README file contents as a string.
    """
    with open("README.md") as file:
        return file.read()


setup(
    name="hyperdrive",
    version=get_version(),
    description="An algorithmic trading platform",
    long_description=get_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/suchak1/hyperdrive",
    author="Krish Suchak",
    author_email="suchak.krish@gmail.com",
    packages=find_packages(),
    python_requires=">=3.7",
    install_requires=get_requirements(),
    project_urls={
        "Bug Reports": "https://github.com/suchak1/hyperdrive/issues",
        "Source": "https://github.com/suchak1/hyperdrive",
    },
)
