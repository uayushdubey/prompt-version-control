#!/usr/bin/env python3
"""
Examples of using promptvc programmatically as a Python library.
This file demonstrates repository initialization, committing prompts with schema,
variable rendering, running prompts with providers, locking versions, and diffing.
"""

import os
import shutil
from promptvc.core import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.utils.template import render_template
from promptvc.core.diff import compute_diff, format_diff

def main():
    # 1. Initialize a temporary promptvc repository for demonstration
    demo_dir = os.path.abspath("./.demo_promptvc")
    if os.path.exists(demo_dir):
        shutil.rmtree(demo_dir)

    print("--- 1. Initializing Repository ---")
    # Initialize repository. By default, StorageEngine looks for '.promptvc' in the current directory.
    # We can inject a custom storage root by subclassing/overriding if needed, but for simplicity,
    # let's use the default repo class or point storage directly to our demo directory.
    repo = PromptRepo()
    # Override storage root path to not pollute actual workspace configuration during demo
    repo.storage._root = repo.storage._root.parent / ".demo_promptvc"
    repo.init_repo()
    print(f"Repository initialized at: {repo.storage._root}")

    # 2. Commit a new prompt space version with variable validation schema
    print("\n--- 2. Committing a Prompt ---")
    prompt_name = "translator"
    prompt_text = "Translate the following text into {{language}}: {{text}}"
    commit_msg = "v1 initial translation prompt"
    
    # Defining a schema is optional but enables validation and defaults
    schema = {
        "variables": {
            "language": {
                "type": "string",
                "required": True,
                "description": "Target language for translation"
            },
            "text": {
                "type": "string",
                "required": True,
                "description": "Source text to translate"
            }
        }
    }

    # Commit prompt template
    meta_v1 = repo.commit(
        name=prompt_name,
        prompt=prompt_text,
        message=commit_msg,
        schema=schema
    )
    print(f"Committed {prompt_name} @ {meta_v1['id']}")
    print(f"Version Hash: {meta_v1['hash']}")
    print(f"Token Count: {meta_v1['tokens']}")

    # 3. Retrieve prompt template and metadata
    print("\n--- 3. Retrieving Prompt and Metadata ---")
    retrieved_prompt = repo.get(prompt_name, "v1")
    print(f"Retrieved Prompt Template: {repr(retrieved_prompt)}")
    
    # Get latest metadata
    latest_meta = repo.latest(prompt_name)
    print(f"Latest Version ID: {latest_meta['id']}")
    print(f"Is Locked: {latest_meta['locked']}")

    # 4. Render prompt templates with variables
    print("\n--- 4. Rendering Prompt Template with Variables ---")
    variables = {
        "language": "Spanish",
        "text": "Hello, world!"
    }
    rendered = render_template(retrieved_prompt, variables)
    print(f"Rendered Prompt:\n  {rendered}")

    # 5. Run prompt against a provider programmatically
    print("\n--- 5. Executing Prompt with Provider ---")
    # For testing, we use MockProvider. In production, you can use OpenAIProvider, etc.
    provider = MockProvider()
    
    # Low-level execution directly through promptvc. This also logs the run record to the storage.
    # Note: repo.run executes the raw prompt template. To execute a rendered prompt,
    # we can pass it directly to the provider.
    run_result = provider.run(rendered)
    print(f"Mock Provider Output: {run_result['output']}")
    print(f"Tokens consumed: {run_result['tokens']}")

    # Logging the run to the repository registry manually
    run_record = {
        "version": "v1",
        "output": run_result["output"],
        "tokens": run_result["tokens"],
        "timestamp": repo._utc_now_iso()
    }
    repo.storage.append_run(prompt_name, run_record)
    print("Logged execution run successfully to registry database.")

    # 6. Commit a new version and compute differences
    print("\n--- 6. Iterating & Diffing Prompts ---")
    updated_prompt_text = "Translate the following text into {{language}} concisely: {{text}}"
    meta_v2 = repo.commit(
        name=prompt_name,
        prompt=updated_prompt_text,
        message="v2 added concise constraint",
        schema=schema
    )
    print(f"Committed {prompt_name} @ {meta_v2['id']}")

    # Compute differences
    token_diff = repo.token_diff(prompt_name, "v1", "v2")
    print(f"Token difference (v2 - v1): {token_diff}")

    diff_lines = compute_diff(prompt_text, updated_prompt_text)
    formatted = format_diff(diff_lines)
    print("Diff output:")
    print(formatted)

    # 7. Locking a version to prevent mutation
    print("\n--- 7. Locking Prompt Version ---")
    repo.lock(prompt_name, "v1")
    print(f"Locked {prompt_name} @ v1")
    
    # Verify locked status
    v1_meta = repo.get_version_meta(prompt_name, "v1")
    print(f"v1 Locked status: {v1_meta['locked']}")

    # Clean up demo repository directory
    if os.path.exists(demo_dir):
        shutil.rmtree(demo_dir)
        print("\nCleaned up demo repository.")

if __name__ == "__main__":
    main()
