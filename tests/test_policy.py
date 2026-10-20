import os

import pytest

from academic_agent.policy import (ACCEPT_EDITS, AUTO, DEFAULT, Approver,
                                   Policy, PolicyError, dangerous_reason,
                                   parse_approval, scrubbed_env,
                                   secret_env_values)


@pytest.fixture
def policy(project):
    return Policy(project)


# ---- confinement ----------------------------------------------------------

def test_relative_path_inside_root(policy, project):
    assert policy.resolve("src/a.py") == project / "src" / "a.py"
    assert policy.resolve(".") == project


@pytest.mark.parametrize("path", [
    "../outside.txt", "src/../../outside.txt", "/etc/passwd", "~/x",
])
def test_paths_outside_root_rejected(policy, path):
    with pytest.raises(PolicyError, match="outside"):
        policy.resolve(path)


def test_absolute_path_inside_root_allowed(policy, project):
    assert policy.resolve(str(project / "a.txt")) == project / "a.txt"


def test_symlink_escaping_root_rejected(policy, project, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    os.symlink(outside, project / "link.txt")
    with pytest.raises(PolicyError, match="outside"):
        policy.resolve("link.txt")


def test_symlinked_directory_escaping_root_rejected(policy, project, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", project / "dir")
    with pytest.raises(PolicyError):
        policy.resolve("dir/file.txt")


def test_symlink_to_secret_rejected(policy, project):
    (project / ".env").write_text("TOKEN=1")
    os.symlink(project / ".env", project / "harmless.txt")
    with pytest.raises(PolicyError, match="not allowed"):
        policy.resolve("harmless.txt")


@pytest.mark.parametrize("path", [
    ".git/config", ".git", "sub/.git/HEAD", ".env", ".env.local",
    "config/.env.production", "certs/server.pem", "id_rsa", "keys/id_ed25519.pub",
])
def test_denied_names(policy, path):
    with pytest.raises(PolicyError, match="not allowed"):
        policy.resolve(path)


def test_similar_names_allowed(policy):
    policy.resolve("environment.py")
    policy.resolve("docs/pem.md")
    policy.resolve("gitignore.txt")


# ---- dangerous-command classifier ----------------------------------------

DANGEROUS = [
    "rm -rf build",
    "rm -r dir",
    "rm -f file",
    "rm --recursive dir",
    "ls && rm -Rf x",
    "git reset --hard",
    "git reset --hard HEAD~1",
    "git clean -fd",
    "git push --force",
    "git push -f origin main",
    "git push --force-with-lease",
    "git push origin +main",
    "git push origin --delete feature",
    "git -C sub push --force",
    "git checkout -- a.py",
    "git stash",
    "git clone https://example.org/x",
    "git fetch",
    "git pull",
    "find . -name '*.pyc' -delete",
    "find . -exec rm -rf {} +",
    "sudo ls",
    "dd if=/dev/zero of=x",
    "mkfs.ext4 x",
    "echo x > /dev/sda",
    "cat /etc/passwd",
    "cp a.txt /tmp/b.txt",
    "ls ../other",
    "cat ~/.ssh/config",
    "echo $HOME",
    "curl https://example.org",
    "wget x",
    "ssh host",
    "scp a host:b",
    "rsync -a . host:x",
    "nc -l 80",
    "pip install requests",
    "pip3 install x",
    "uv pip install x",
    "python -m pip install x",
    "python3 -m pip install x",
    "npm install",
    "yarn add left-pad",
    "pnpm i",
    "apt-get install x",
    "apt install x",
    "bash -c 'rm -rf x'",
    "sh -c \"git push -f\"",
    "FOO=1 rm -rf x",
    "env rm -rf x",
    "xargs rm -rf",
    "ls | xargs rm -f",
    "true\nrm -rf x",
    "echo 'unterminated",
    "python --out=/etc/x",
    "git commit -F /etc/passwd",
    "git commit -m ok && cat /etc/passwd",
]

SAFE = [
    "ls -la",
    "pytest -q",
    "python -m pytest",
    "git status",
    "git diff",
    "git log --oneline HEAD~3..HEAD",
    "git show HEAD~1",
    "git checkout feature",
    "git add -A && git commit -m 'Fix parser'",
    "git push",
    "git push -u origin feature/x",
    "git -C sub push origin HEAD",
    "git reset HEAD a.txt",
    "git reset --soft HEAD~1",
    "gh pr create --title 'Fix' --body 'Details'",
    "gh pr view 12",
    "git commit -m 'Add /undo and ~ handling, see ../README'",
    "git commit --message='Fix /etc parsing'",
    "gh pr create --title '/diff command' --body 'Uses $HOME and /tmp'",
    "rm build/old.txt",
    "find . -name '*.py'",
    "echo hi > out.txt",
    "make test 2>/dev/null",
    "ls > /dev/null 2>&1",
    "grep -rn 'rm -rf' src",
    "pip list",
    "pip show requests",
    "npm run build",
    "npm test",
    "cat ./a.txt src/b.py",
    "sed -i 's/a/b/' f.txt",
    "python -c 'print(1)'",
    "echo 'a\nb'",
]


@pytest.mark.parametrize("command", DANGEROUS)
def test_dangerous(command, project):
    assert dangerous_reason(command, project) is not None


@pytest.mark.parametrize("command", SAFE)
def test_safe(command, project):
    assert dangerous_reason(command, project) is None


def test_absolute_path_inside_root_is_not_dangerous(project):
    assert dangerous_reason(f"cat {project}/a.txt", project) is None


# ---- approval tiers -------------------------------------------------------

def test_tiers_default():
    a = Approver(DEFAULT)
    assert not a.needs_prompt("read_file")
    assert a.needs_prompt("edit_file")
    assert a.needs_prompt("run")
    a.allow_always("edit_file")
    assert not a.needs_prompt("edit_file")
    assert a.needs_prompt("write_file")


def test_tiers_accept_edits():
    a = Approver(ACCEPT_EDITS)
    assert not a.needs_prompt("write_file")
    assert not a.needs_prompt("delete_file")
    assert a.needs_prompt("run")
    assert a.needs_prompt("run", dangerous=True)


def test_tiers_auto_approve_still_asks_for_dangerous():
    a = Approver(AUTO)
    assert not a.needs_prompt("edit_file")
    assert not a.needs_prompt("run")
    assert a.needs_prompt("run", dangerous=True)


def test_always_never_covers_dangerous():
    a = Approver(DEFAULT)
    a.allow_always("run")
    assert not a.needs_prompt("run")
    assert a.needs_prompt("run", dangerous=True)


@pytest.mark.parametrize("answer, expected", [
    ("y", ("yes", "")), ("YES", ("yes", "")), ("", ("no", "")),
    ("n", ("no", "")), ("a", ("always", "")),
    ("use pathlib instead", ("comment", "use pathlib instead")),
])
def test_parse_approval(answer, expected):
    assert parse_approval(answer) == expected


# ---- environment ----------------------------------------------------------

def test_scrubbed_env():
    env = {
        "PATH": "/bin", "HOME": "/home/u", "ACADEMIC_AI_CLIENT_SECRET": "s3cr3t!",
        "ACADEMIC_AI_MODEL": "m", "GITHUB_TOKEN": "ghp_abcdef", "AWS_SECRET_ACCESS_KEY": "k",
        "db_password": "hunter22", "API_KEY": "x",
    }
    assert scrubbed_env(env) == {"PATH": "/bin", "HOME": "/home/u"}
    assert set(secret_env_values(env)) == {"s3cr3t!", "ghp_abcdef", "hunter22"}
