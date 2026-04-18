from setuptools import setup, find_packages

setup(
    name="promptvc",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        "console_scripts": [
            "promptvc=promptvc.cli.main:main",
        ],
    },
)