from setuptools import setup

with open("README.md") as f:
    long_description = f.read()

setup(
    name="jupyterhub-acispawner",
    version="0.0.1",
    description="JupyterHub Spawner using Azure Container Image for resource isolation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/lcrownover/acispawner",
    author="Lucas Crownover",
    author_email="lcrownover127@gmail.com",
    license="3 Clause BSD",
    packages=["acispawner"],
    entry_points={
        "jupyterhub.spawners": [
            "acispawner = acispawner:ACISpawner",
        ],
    },
    install_requires=[
        "jupyterhub>=0.9",
        "tornado>=5.0",
        "azure-mgmt-containerinstance>=1.5.0",
        "msrestazure",
        "azure-identity",
    ],
)
