import json


def run_evaluation(
    repo,
    name: str,
    version: str,
    dataset_path: str,
    provider,
) -> dict:
    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in dataset file '{dataset_path}': {e}") from e

    if not isinstance(dataset, list):
        raise ValueError(
            f"Dataset must be a JSON array, got {type(dataset).__name__}."
        )

    prompt_text = repo.get(name, version)

    results = []
    for index, item in enumerate(dataset):
        if not isinstance(item, dict) or "input" not in item:
            raise ValueError(
                f"Dataset item at index {index} is missing required 'input' field."
            )

        input_text = item["input"]
        full_prompt = f"{prompt_text}\n\n{input_text}"
        result = provider.run(full_prompt)

        output = result.get("output")
        if output is None:
            raise ValueError(
                f"Provider returned no output for dataset item at index {index}."
            )

        results.append(
            {
                "input": input_text,
                "output": output,
                "tokens": result.get("tokens"),
            }
        )

    return {
        "version": version,
        "dataset": dataset_path,
        "results": results,
    }