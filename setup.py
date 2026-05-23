from setuptools import setup, find_packages

setup(
    name="promptvc",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests",
    ],
    extras_require={
        "openai": ["openai"],
        "gemini": ["google-generativeai"],
        "anthropic": ["anthropic"],
        "all": ["openai", "google-generativeai", "anthropic"],
    },
    entry_points={
        "console_scripts": [
            "promptvc=promptvc.cli.main:main",
        ],
    },
)