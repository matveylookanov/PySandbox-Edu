import logging
import os
import time
from typing import Optional

import docker
from docker.errors import DockerException, ContainerError, APIError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr


logger = logging.getLogger("pysandbox")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


MAX_CODE_LENGTH = 10_000
MEMORY_LIMIT = os.getenv("MEMORY_LIMIT", "128m")
NANO_CPUS = int(os.getenv("NANO_CPUS", "500000000"))  # 0.5 CPU
EXECUTOR_IMAGE = os.getenv("EXECUTOR_IMAGE", "pysandbox-executor")
EXECUTION_TIMEOUT_SECONDS = int(os.getenv("EXECUTION_TIMEOUT_SECONDS", "10"))


class ExecuteRequest(BaseModel):
    code: constr(max_length=MAX_CODE_LENGTH)  # type: ignore[call-arg]


class ExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


app = FastAPI(title="PySandbox Edu API")


origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


docker_client: Optional[docker.DockerClient] = None


@app.on_event("startup")
def startup_event() -> None:
    global docker_client
    try:
        docker_client = docker.from_env()
        # simple ping to check connectivity
        docker_client.ping()
        logger.info("Connected to Docker daemon successfully.")
    except DockerException as exc:
        logger.error("Failed to connect to Docker daemon: %s", exc)
        docker_client = None


@app.middleware("http")
async def log_requests(request, call_next):
    start_time = time.monotonic()
    logger.info("Incoming request: %s %s", request.method, request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error during request processing")
        raise
    duration_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(
        "Completed request: %s %s -> %s in %d ms",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/")
async def root():
    return {"message": "PySandbox Edu backend is running."}


@app.get("/health")
async def health():
    if docker_client is None:
        return {"status": "degraded", "docker": False}
    try:
        docker_client.ping()
        return {"status": "ok", "docker": True}
    except DockerException:
        logger.exception("Docker health check failed")
        return {"status": "degraded", "docker": False}


def _build_python_command(code: str) -> str:
    # Use a here-doc to safely pass multi-line code to python
    return "python - << 'EOF'\n" + code + "\nEOF"


def _ensure_docker_client() -> docker.DockerClient:
    if docker_client is None:
        raise HTTPException(
            status_code=500,
            detail="Docker client is not available. Check Docker daemon and socket permissions.",
        )
    return docker_client


def run_code_in_container(code: str) -> ExecuteResponse:
    client = _ensure_docker_client()
    command = _build_python_command(code)

    start = time.monotonic()

    try:
        container = client.containers.run(
            EXECUTOR_IMAGE,
            command=["/bin/sh", "-c", command],
            network_disabled=True,
            mem_limit=MEMORY_LIMIT,
            nano_cpus=NANO_CPUS,
            detach=True,
            stdin_open=False,
            stdout=True,
            stderr=True,
            remove=True,
        )

        try:
            wait_result = container.wait(timeout=EXECUTION_TIMEOUT_SECONDS)
            exit_code = int(wait_result.get("StatusCode", -1))
            logs_bytes = container.logs(stdout=True, stderr=True)
            logs = logs_bytes.decode("utf-8", errors="replace")
            duration_ms = int((time.monotonic() - start) * 1000)

            stdout_lines = []
            stderr_lines = []
            for line in logs.splitlines():
                if line.startswith("STDERR:"):
                    stderr_lines.append(line[len("STDERR:") :])
                else:
                    stdout_lines.append(line)

            stdout = "\n".join(stdout_lines).strip()
            stderr = "\n".join(stderr_lines).strip()

            logger.info(
                "Execution finished: exit_code=%d, duration_ms=%d", exit_code, duration_ms
            )
            return ExecuteResponse(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            # Best-effort kill in case of timeout or other error
            try:
                container.kill()
            except Exception:
                logger.warning("Failed to kill container after error.")
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Error while waiting for container: %s", exc)
            raise HTTPException(
                status_code=500,
                detail=f"Execution failed or timed out after {EXECUTION_TIMEOUT_SECONDS} seconds.",
            )

    except ContainerError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.exception("Container error during execution: %s", exc)
        return ExecuteResponse(
            stdout="",
            stderr=str(exc),
            exit_code=1,
            duration_ms=duration_ms,
        )
    except (DockerException, APIError) as exc:
        logger.exception("Docker error during execution: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to start execution container. Check executor image and Docker daemon.",
        )


@app.post("/execute", response_model=ExecuteResponse)
async def execute(request: ExecuteRequest):
    logger.info("Received execute request (code length=%d).", len(request.code))
    if len(request.code) > MAX_CODE_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Code is too long. Max length is {MAX_CODE_LENGTH} characters.",
        )

    return run_code_in_container(request.code)

