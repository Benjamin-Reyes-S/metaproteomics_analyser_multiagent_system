"""Deterministic sandbox execution boundary.

run_code() builds and runs a fixed, non-negotiable Docker command:

    docker run --rm --name <container_name> --network none \\
        -v <input_dir>:/input:ro \\
        -v <workspace_dir>:/workspace \\
        -w /workspace \\
        <image> python /workspace/code.py

The command is assembled entirely by this function. No agent or LLM
output ever contributes to the command itself -- only the contents of
workspace/code.py (already written to disk by the caller) are executed.

Each run gets a unique --name. On timeout, killing the subprocess only stops
the docker CLI, not the container (the host daemon owns it), so run_code()
also runs `docker kill <container_name>`; --rm then removes it.
"""

import subprocess
import uuid
from pathlib import Path

IMAGE_NAME = "metaproteomics-sandbox:latest"
CONTAINER_NAME_PREFIX = "metaproteomics-sandbox-run"
TIMEOUT_SECONDS = 3600  # 1 h: input/ holds ~420 MB of CSVs; 300 s was too short
KILL_TIMEOUT_SECONDS = 30


def _kill_container(container_name: str) -> str:
    """Stop a still-running sandbox container; returns a note for stderr."""
    try:
        killed = subprocess.run(
            ["docker", "kill", container_name],
            capture_output=True, text=True, timeout=KILL_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"[run_code] docker kill {container_name} failed: {exc}\n"
    if killed.returncode == 0:
        return f"[run_code] killed container {container_name}\n"
    return f"[run_code] docker kill {container_name} failed: {killed.stderr.strip()}\n"


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
    container_name = f"{CONTAINER_NAME_PREFIX}-{uuid.uuid4().hex[:12]}"

    command = [
        "docker", "run", "--rm",
        "--name", container_name,
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
        # exc.stdout/stderr can be bytes even with text=True
        stdout, stderr = (
            (value.decode(errors="replace") if isinstance(value, bytes) else value or "")
            for value in (exc.stdout, exc.stderr)
        )
        stderr += f"\n[run_code] timed out after {timeout}s\n"
        stderr += _kill_container(container_name)
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
