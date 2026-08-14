"""Deterministic sandbox execution boundary.

run_code() builds and runs a fixed, non-negotiable Docker command:

    docker run --rm --network none \\
        -v <input_dir>:/input:ro \\
        -v <workspace_dir>:/workspace \\
        -w /workspace \\
        <image> python /workspace/code.py

The command is assembled entirely by this function. No agent or LLM
output ever contributes to the command itself -- only the contents of
workspace/code.py (already written to disk by the caller) are executed.
"""

import subprocess
from pathlib import Path

IMAGE_NAME = "metaproteomics-sandbox:latest"
TIMEOUT_SECONDS = 300


def run_code(
    workspace_dir: Path,
    input_dir: Path,
    image: str = IMAGE_NAME,
    timeout: int = TIMEOUT_SECONDS,
) -> dict:
    """Execute /workspace/code.py inside the sandbox container.

    Expects `workspace_dir / "code.py"` to already exist. Returns a dict
    with stdout, stderr, exit_code, and output_files (every file left in
    workspace_dir afterwards, excluding code.py itself).
    """
    workspace_dir = Path(workspace_dir).resolve()
    input_dir = Path(input_dir).resolve()

    command = [
        "docker", "run", "--rm",
        "--network", "none",
        "-v", f"{input_dir}:/input:ro",
        "-v", f"{workspace_dir}:/workspace",
        "-w", "/workspace",
        image,
        "python", "/workspace/code.py",
    ]

    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\n[run_code] timed out after {timeout}s\n"
        exit_code = -1
    except FileNotFoundError as exc:
        stdout = ""
        stderr = f"[run_code] failed to launch docker: {exc}\n"
        exit_code = -1

    output_files = sorted(
        str(path) for path in workspace_dir.iterdir()
        if path.is_file() and path.name != "code.py"
    )

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "output_files": output_files,
    }
