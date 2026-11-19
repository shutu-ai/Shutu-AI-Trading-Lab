# RD-Agent (Microsoft) — M-1 POC Evaluation Evidence

- Evaluated: 2026-11-19, host Windows 11 Pro (10.0.26200), Python 3.13.15 (`py -3.13`)
- Clone: `third_party/RD-Agent` @ 484776c211e4fbbeef03e0ec00d6bbee7362a4f4 (= tag `v1.0.0`, commit msg "chore(main): release 1.0.0 (#1286)"), clean tree
- Venv: `third_party/.venv-rdagent` (dedicated)
- Log refs below are under `artifacts/evidence/M-1/candidates/rdagent/logs/`

---

## [Install] — PASS

- Command: `HTTPS_PROXY=http://192.168.1.2:8080 HTTP_PROXY=http://192.168.1.2:8080 third_party/.venv-rdagent/Scripts/python.exe -m pip install rdagent` (all traffic via proxy 192.168.1.2:8080)
- Result: **exit 0**, `Successfully installed ... rdagent-1.0.0 ...` — installs cleanly on Python 3.13.15 / Windows 11. Log: `logs/install.txt` (full transcript; all wheels resolved, incl. cp313 wheels for tree-sitter, pymupdf, tables 3.11.1, pyarrow 26; only `pandarallel`/`randomname` needed local wheel builds — both succeeded).
- Dependency count: **286 packages** (`pip list` → `logs/piplist.txt`, `TOTAL_PACKAGES=286`).
- Heavy deps confirmed installed: litellm 1.110.1, langchain 1.5.2 (+ langchain-community 0.4.2, langgraph 1.2.23), mlflow 3.18.0, prefect 3.9.3, docker SDK 7.2.0, openai 3.55.1, pydantic-ai-slim 1.66.0, streamlit 1.67.0, selenium 4.53.0, datasets 5.2.0, tensorboard 2.21.0, azure SDKs (identity / ai.formrecognizer / ai.inference / mlflow), pymupdf 2.1, pandas 3.1.1, numpy 2.5.5.
- **torch NOT installed** (count 0 in `logs/piplist.txt`) — torch is an optional extra `pip install rdagent[torch]` (pyproject.toml:123 "some agent algorithms need torch").

## [Version] — PASS

- PyPI version installed: **rdagent 1.0.0** (`logs/install.txt`, `logs/piplist.txt` pip show).
- Cross-check vs pinned SHA: clone HEAD 484776c is exactly the `v1.0.0` release commit → **PyPI 1.0.0 matches the pinned SHA exactly** (not just "roughly").
- Note: `import rdagent; rdagent.__version__` → attribute does not exist, prints `n/a` (coded that way). Version is available via `importlib.metadata.version('rdagent') = 1.0.0`. Log: `logs/import_cli.txt`.

## [License] — PASS

- `LICENSE`: "MIT License — Copyright (c) Microsoft Corporation." (full text head in `logs/code_inspection.txt` [L1]).
- `pyproject.toml:14`: classifier `License :: OSI Approved :: MIT License`.
- MIT = low license risk for internal/commercial integration.

## [CLI] — PASS (LLM-dependent subcommands: BLOCKED_ENV)

- `python -c "import rdagent; ..."` → exit 0, `n/a` (`logs/import_cli.txt`).
- `rdagent --help` → **exit 0**; 13 commands listed: `fin_factor, fin_model, fin_quant, fin_factor_report, general_model, data_science, llm_finetune, grade_summary, ui, server_ui, health_check, collect_info, ds_user_interact`. Log: `logs/import_cli.txt`.
- Console script per `pyproject.toml:35`: `rdagent = "rdagent.app.cli:app"` (Typer app; loads `.env` from cwd on start — cli.py:13).
- Cold start of `rdagent --help` on this host: **91 s** (heavy import chain; a `fitz` FutureWarning is printed). Log: `logs/import_cli.txt`.
- `rdagent health_check` → runs on Windows without Docker; emits env warning ("We did not find BACKEND in your configuration…add it to your .env"), attempts LLM connectivity test → `litellm.BadRequestError: GetLLMProvider Exception - model parameter is required but was None` (no credentials configured — expected here). Log: `logs/health_check.txt`.

## [Non-LLM capabilities] — PASS for what was verified; end-to-end loop BLOCKED_ENV

Quant factor/model scenario support (code paths, clone-verified):
- Scenarios: `rdagent/scenarios/qlib/` (factor / model / quant experiments: `experiment/factor_experiment.py`, `experiment/model_experiment.py`, `experiment/quant_experiment.py`, `proposal/factor_proposal.py`, `proposal/model_proposal.py`, `proposal/quant_proposal.py`, `developer/factor_coder.py`, `factor_runner.py`, `model_coder.py`, `model_runner.py`, `feedback.py`).
- Loop apps: `rdagent/app/qlib_rd_loop/{factor,model,quant,factor_from_report}.py` + `conf.py` (env prefixes `QLIB_FACTOR_`, `QLIB_MODEL_`, `QLIB_QUANT_`).
- Other scenarios shipped: data_science (Kaggle/MLE-Bench), finetune (LLaMA-Factory), general_model, rl, kaggle (`rdagent/scenarios/` listing in `logs/code_inspection.txt` [L21]).
- Factor-loop specifics verified in code: IC-based dedup of new factors vs SOTA (`factor_runner.py:35-61`), parquet handoff to qlib (`factor_runner.py:124-130`), combined-factors backtest configs (`factor_runner.py:164-193`).

What runs without LLM keys (verified on this host): package import, `--help`, settings instantiation (`logs/llm_probe.txt` — LLM_SETTINGS loads with empty keys, exit 0), health_check partial run, streamlit UI (not launched here — UNVERIFIED).
What cannot run without LLM keys: every research loop (first step is hypothesis generation via LLM). Verified failure text (`logs/llm_probe.txt`):
```
litellm.InternalServerError: OpenAIException - Missing credentials. Please pass an `api_key`, `workload_identity`, `admin_api_key`, or set the `OPENAI_API_KEY` or `OPENAI_ADMIN_KEY` environment variable.
→ (10 retries) RuntimeError: Failed to create chat completion after 10 retries.
```
- No-LLM dry-run mode: **none found** (grep `dry.?run|no_llm|mock_llm|offline_mode` over `rdagent/`, `docs/`, README → only an unrelated prompt string; `logs/code_inspection.txt` [L23]). Closest facilities: pytest `offline` marker (pyproject.toml:74-75) and an LLM response cache (`use_chat_cache`, `prompt_cache_path`, llm_conf.py:43-47) that replays a pre-populated sqlite cache — replay-mode runs UNVERIFIED (not exercised here).

## [Docker requirement] — code-verified facts; execution BLOCKED_ENV on this host (no Docker installed)

- README:137-138 (quote): "### 🐳 Docker installation. Users must ensure Docker is installed before attempting most scenarios. … Ensure the current user can run Docker commands **without using sudo**."
- Docker SDK is a hard runtime dependency (`requirements.txt:41` `docker`; module-level `import docker` at `rdagent/utils/env.py:40-43`).
- BUT the qlib quant execution backend is **switchable docker/conda**: `rdagent/scenarios/qlib/experiment/workspace.py:19-24` (quote in `logs/code_inspection.txt` [L13]):
  ```python
  if MODEL_COSTEER_SETTINGS.env_type == "docker":   qtde = QTDockerEnv()
  elif MODEL_COSTEER_SETTINGS.env_type == "conda":  qtde = QlibCondaEnv(conf=QlibCondaConf())
  ```
  Default is **conda**, not docker: `rdagent/components/coder/model_coder/conf.py` — `env_type: str = "conda"  # or "docker"` (env prefix `MODEL_CoSTEER_`).
  - Docker path: `QlibDockerConf` (`rdagent/utils/env.py:1042-1062`) builds image `local_qlib:latest` from `rdagent/scenarios/qlib/docker/Dockerfile` (pytorch/pytorch:2.2.1-cuda12.1 base; clones qlib pinned `2fb9380b`; [L28]), mounts workspace at `/workspace/qlib_workspace/`, entry `qrun conf.yaml`, shm 16g, GPU default on.
  - Conda path: `QlibCondaEnv.prepare()` (`rdagent/utils/env.py:855-880`, [L10]) auto-creates conda env `rdagent4qlib` (python=3.10) and installs qlib from the same pinned git SHA + catboost/xgboost/tables/torch.
  - Exception: the **factor-coding step always uses `LocalEnv`** (current conda env), `rdagent/components/coder/factor_coder/config.py:36-37` (`get_factor_env` → `LocalEnv(CondaConf(conda_env_name=os.environ.get("CONDA_DEFAULT_ENV")))`, [L29]).
- This host: `docker` CLI absent (`command not found`, exit 127) and docker SDK raises `docker.errors.DockerException: Error while fetching server API version: (2, 'CreateFile', …)` (missing named pipe). Log: `logs/docker_probe.txt`. → Docker-backed paths are BLOCKED_ENV here; they were **not** re-run inside a Docker-capable host (UNVERIFIED end-to-end).

## [LLM backends] — PASS (config-level; actual API calls BLOCKED_ENV)

- Default backend: **LiteLLM** — `rdagent/oai/llm_conf.py:13` `backend: str = "rdagent.oai.backend.LiteLLMAPIBackend"`; `chat_model = "gpt-4-turbo"`, `embedding_model = "text-embedding-3-small"` (llm_conf.py:15-16). Via LiteLLM, any provider string litellm supports (OpenAI, Azure OpenAI, DeepSeek, Anthropic, Gemini, Ollama/vLLM proxies, …) is addressable — docs instruct provider params to "align with those required by LiteLLM" (`docs/installation_and_configuration.rst:92-100`, [L20]).
- Azure OpenAI: first-class flags `chat_use_azure`, `embedding_use_azure`, `chat_azure_api_base/version`, Azure Token Provider + managed identity (`llm_conf.py:34-40, 67-68`; docs:414-469).
- DeepSeek: documented experimental support, `CHAT_MODEL=deepseek/deepseek-chat` + `DEEPSEEK_API_KEY` (docs:20, 54-65).
- Second backend: **pydantic-ai** adapter (`rdagent/oai/backend/pydantic_ai.py`) — wraps LiteLLM; provider env map `{openai, azure_ai, azure, litellm_proxy}` ([L17]).
- Legacy backend `DeprecBackend` (`rdagent/oai/backend/deprec.py`): raw `openai` SDK + `azure.identity`, plus deprecated offline llama2 / Azure GCR endpoints (llama2/llama3-70b, phi2/phi3) — llm_conf.py:92-124.
- Model aliasing: `chat_model_map: dict[str, dict[str,str]]` (llm_conf.py:130).
- Cost observability: per-call + accumulated USD cost logged at runtime via litellm `completion_cost` (`rdagent/oai/backend/litellm.py:195-220`, [L16]).

## [Windows compat] — partial PASS (facts below are code-verified unless marked INFERENCE/UNVERIFIED)

Works on Windows 11 / Py3.13 (verified in this session):
- pip install, `import rdagent`, `rdagent --help`, settings load, health_check startup (`logs/*.txt`).

Broken/blocked on a native Windows host (code cites):
1. `rdagent/utils/env.py:430-443` — **every** `Env.run` entry (Docker **and** conda/local) is wrapped as `/bin/sh -c 'timeout --kill-after=10 <n> <entry>; …'` ([L7]). On Windows, `LocalEnv` executes this via `subprocess.Popen(shell=True)` → cmd.exe → `/bin/sh` and GNU `timeout` do not exist. The conda (default) path is therefore not runnable as-shipped on Windows. Also `chmod -R 777` (env.py:417) in the DockerConf branch — harmless inside Linux containers only.
2. `rdagent/utils/env.py:707` — `LocalEnv` live-output path uses `select.poll()`, which does not exist in Python on Windows → AttributeError (`LocalConf.live_output` defaults True, env.py:596, [L34]).
3. `rdagent/utils/env.py:142` — `docker.APIClient(base_url="unix://var/run/docker.sock")` hardcoded Unix socket (image-pull progress helper used by GPU test path, [L9]).
4. `rdagent/utils/env.py:769-776` — `CondaConf._update_bin_path` runs `conda run -n <env> env | grep '^PATH='` via shell=True ([L30]) — `env`/`grep` are not Windows commands (fails silently → empty bin_path).
5. Unix-absolute cache paths `/tmp/sample`, `/tmp/full` (env.py:623, 1468-1469).
6. Console logging: loguru/colorama sink raises `UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f680'` repeatedly on this zh-CN-locale Windows host (emoji in log messages; `logs/health_check.txt`). Non-fatal but noisy.
- INFERENCE (not executed here): the Docker path itself is Windows-viable with Docker Desktop/WSL2 — `docker.from_env()` supports npipe (the probe failed only because no Docker is installed), and the `/bin/sh`/`timeout`/`chmod` wrapper executes inside the Linux container. README itself only says "most scenarios" need Docker and links generic install docs; one error string references Ubuntu docs (`health_check.py:26`).
- UNVERIFIED: end-to-end loop on any host (LLM keys missing); pandarallel behavior on Windows (`factor_runner.py:9` uses it; officially Linux/macOS-leaning); streamlit UI on Windows.

Practical verdict: treat RD-Agent as a **Linux(-container)/WSL2 workload**, not a native-Windows one.

## [Assessment]

Fit for M-4-style AI research factory (factor/model research loop):
- Scenario depth is real and quant-specific: hypothesis → experiment spec → LLM code-gen (CoSTEER, evolving_n=10 per proposal) → qlib execution → IC-dedup vs SOTA → structured feedback, with separate factor / model / combined quant loops and a factor-from-research-report pipeline. This matches an "AI research factory" shape more closely than generic agent frameworks.
- Integration surface: RD-Agent owns its loop (`RDLoop`/`LoopBase`, per-step session dump/load/resume; `rdagent/utils/workflow/loop.py:308,455`). Components are injected by import-path strings (`FACTOR_PROP_SETTING.runner = "…QlibFactorRunner"` etc., `app/qlib_rd_loop/conf.py`), so a wrapper registry can replace the Runner/Summarizer classes to mirror every executed experiment into our own registry, and consume its trace logs (`log/<ts>/…`, sqlite/streamlit UI, `rdagent server_ui`). You do NOT drive it step-by-step from outside; you either wrap the runner boundary or accept its loop.
- Execution isolation: generated factor/model code always executes in its managed env (docker container or conda env), never in the orchestrator process. README:436 explicitly warns to run workers "in an isolated, least-privileged environment with restricted network egress and no host credentials or Docker socket exposed to generated code."
- Operational cost: no published per-iteration token/cost figure in docs or code (grep — UNVERIFIED). Runtime accumulators exist (`ACC_COST` per call, litellm.py:195-220) so real spend is measurable per run. Cost drivers are concrete: `evolving_n=10` code-evolution rounds per proposal × ~5 steps/loop × loop_n, default model gpt-4-turbo. Experiment re-runs are pickle-cached (`env.py:470-516`), LLM responses optionally cached (`use_chat_cache`) — cost control exists but is opt-in.
- License: MIT (Microsoft) — no copyleft risk. Dependency risk: large (286 packages; langchain, mlflow, prefect, streamlit, azure SDKs, selenium all installed even for quant-only use); torch avoidable via base install.

Top risks:
1. **Platform mismatch**: POSIX/Docker assumptions everywhere in execution paths; native Windows host not viable (env.py:431 `/bin/sh`, :707 `select.poll`, :142 unix socket). Deployment target must be Linux/WSL2 — affects our sandbox design.
2. **LLM spend unquantified + aggressive defaults**: gpt-4-turbo default, 10 evolutions/proposal, no dry-run mode; cannot be bounded before first billed run (BLOCKED_ENV here). Budget guardrails must be built by us (model swap via `CHAT_MODEL`/`chat_model_map`, cache on, cost logging via ACC_COST).
3. **Stack drift**: package claims Python 3.10/3.11 classifiers (works on 3.13 for install/CLI, but untested by upstream); qlib execution env pins python=3.10 + qlib git SHA `2fb9380b` — a second, older Python runtime to maintain inside the sandbox; security surface of executing LLM-generated code (needs network-restricted containers, per README's own warning).

UNVERIFIED items: end-to-end factor loop (LLM keys absent — BLOCKED_ENV); actual per-iteration token cost; Docker-path run on a Docker-capable host; `use_chat_cache` replay mode; streamlit UI; pandarallel on Windows.
