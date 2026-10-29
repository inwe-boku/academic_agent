import os
import shutil
import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parent.parent / "academic"


def run_launcher(tmp_path, env_file: str, **env):
    """Run a copy of the launcher whose 'python' prints the model setting."""
    app = tmp_path / "app"
    (app / ".venv" / "bin").mkdir(parents=True)
    shutil.copy(LAUNCHER, app / "academic")
    python = app / ".venv" / "bin" / "python"
    python.write_text('#!/bin/sh\necho "model=$ACADEMIC_AI_MODEL url=$ACADEMIC_AI_BASE_URL"\n')
    python.chmod(0o755)
    config = tmp_path / "config" / "academic-agent"
    config.mkdir(parents=True)
    (config / "env").write_text(env_file)
    (config / "env").chmod(0o600)
    base = {k: v for k, v in os.environ.items() if not k.startswith("ACADEMIC_AI_")}
    base.update(XDG_CONFIG_HOME=str(tmp_path / "config"), **env)
    return subprocess.run([str(app / "academic")], env=base, capture_output=True,
                          text=True, check=True).stdout.strip()


CONFIG = ('export ACADEMIC_AI_MODEL="gpt-5"\n'
          'export ACADEMIC_AI_BASE_URL="https://from-file"\n')


def test_config_file_used_by_default(tmp_path):
    assert run_launcher(tmp_path, CONFIG) == "model=gpt-5 url=https://from-file"


def test_caller_environment_overrides_config_file(tmp_path):
    out = run_launcher(tmp_path, CONFIG, ACADEMIC_AI_MODEL="claude-opus-4-8 'quoted'")
    assert out == "model=claude-opus-4-8 'quoted' url=https://from-file"
