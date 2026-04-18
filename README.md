# promptvc

Git for prompts.

## Features
- version prompts
- diff changes
- run prompts
- track execution history

## Usage

```bash
promptvc init
promptvc commit chatbot --prompt "hello" --message "v1"
promptvc run chatbot v1


---

##  Add `setup.py` or `pyproject.toml`

So others can install:

```bash
pip install -e .

git tag v0.1.0
git push origin v0.1.0
