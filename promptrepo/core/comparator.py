from promptrepo.core.evaluator import run_evaluation


def compare_versions(
    repo,
    name: str,
    v1: str,
    v2: str,
    dataset_path: str,
    provider,
) -> dict:
    eval1 = run_evaluation(repo, name, v1, dataset_path, provider)
    eval2 = run_evaluation(repo, name, v2, dataset_path, provider)

    results1 = eval1["results"]
    results2 = eval2["results"]

    if len(results1) != len(results2):
        raise ValueError(
            f"Result length mismatch: '{v1}' returned {len(results1)} cases, "
            f"'{v2}' returned {len(results2)} cases."
        )

    comparisons = []
    for i, (r1, r2) in enumerate(zip(results1, results2)):
        if r1.get("output") is None:
            raise ValueError(f"Missing output for '{v1}' at case index {i}.")
        if r2.get("output") is None:
            raise ValueError(f"Missing output for '{v2}' at case index {i}.")

        comparisons.append(
            {
                "input": r1["input"],
                "v1_output": r1["output"],
                "v2_output": r2["output"],
                "v1_tokens": r1["tokens"],
                "v2_tokens": r2["tokens"],
            }
        )

    return {
        "v1": v1,
        "v2": v2,
        "dataset": dataset_path,
        "comparisons": comparisons,
    }
