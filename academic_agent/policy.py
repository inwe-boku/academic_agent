"""Path confinement, approval tiers and the dangerous-command check."""

import fnmatch
import os
import re
import shlex
from pathlib import Path

SECRET_NAME_PATTERNS = (".env*", "*.pem", "id_*")

# Environment variables removed before running shell commands.
SECRET_ENV_PATTERNS = ("ACADEMIC_AI_*", "*TOKEN*", "*SECRET*", "*KEY*", "*PASSWORD*")

# Set for commands the agent runs, so that they cannot start the agent again.
NESTED_ENV = "ACADEMIC_AGENT_NESTED"

TIERS = {
    "read_file": "read",
    "list_dir": "read",
    "search": "read",
    "edit_file": "write",
    "write_file": "write",
    "move_file": "write",
    "delete_file": "write",
    "run": "exec",
    "remember": "memory",
}

# Approval modes
DEFAULT = "default"
ACCEPT_EDITS = "accept-edits"
AUTO = "auto-approve"


class PolicyError(Exception):
    """A path or action is not allowed."""


def is_secret_name(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in SECRET_NAME_PATTERNS)


def is_denied_rel(rel_parts) -> bool:
    """True for paths inside .git/ or with a secret-like component."""
    return any(part == ".git" or is_secret_name(part) for part in rel_parts)


class Policy:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        """Resolve a model-supplied path; reject anything outside the root."""
        if not isinstance(path, str) or "\0" in path:
            raise PolicyError("invalid path")
        raw = Path(path).expanduser() if path.startswith("~") else Path(path)
        lexical = Path(os.path.normpath(self.root / raw))
        resolved = lexical.resolve()
        for candidate in (lexical, resolved):
            try:
                rel = candidate.relative_to(self.root)
            except ValueError:
                raise PolicyError(f"{path}: outside the project root") from None
            if is_denied_rel(rel.parts):
                raise PolicyError(f"{path}: access to this file is not allowed")
        return resolved

    def rel(self, path: Path) -> str:
        rel = path.relative_to(self.root).as_posix()
        return rel or "."


def scrubbed_env(env=None) -> dict:
    env = dict(os.environ if env is None else env)
    return {
        k: v
        for k, v in env.items()
        if not any(fnmatch.fnmatchcase(k.upper(), p) for p in SECRET_ENV_PATTERNS)
    }


def secret_env_values(env=None) -> list[str]:
    """Values of the variables stripped by scrubbed_env (for redaction)."""
    env = dict(os.environ if env is None else env)
    kept = scrubbed_env(env)
    return [v for k, v in env.items() if k not in kept and len(v) >= 6]


# ---- Approval -------------------------------------------------------------

class Approver:
    """Decides which actions need an interactive confirmation."""

    def __init__(self, mode: str = DEFAULT):
        self.mode = mode
        self.always: set[str] = set()

    def needs_prompt(self, tool: str, dangerous: bool = False) -> bool:
        tier = TIERS[tool]
        if tier in ("read", "memory"):
            return False
        if tier == "exec" and dangerous:
            return True
        if self.mode == AUTO:
            return False
        if tier == "write" and self.mode == ACCEPT_EDITS:
            return False
        return tool not in self.always

    def allow_always(self, tool: str) -> None:
        self.always.add(tool)


def parse_approval(answer: str) -> tuple[str, str]:
    """Map prompt input to ('yes'|'no'|'always'|'comment', comment)."""
    text = answer.strip()
    low = text.lower()
    if low in {"y", "yes"}:
        return "yes", ""
    if low in {"", "n", "no"}:
        return "no", ""
    if low in {"a", "always"}:
        return "always", ""
    return "comment", text


# ---- Dangerous commands ---------------------------------------------------

_OPERATORS = {";", ";;", "&&", "||", "|", "&", "|&", "(", ")", "((", "))"}
_WRAPPERS = {"env", "command", "nohup", "time", "nice", "exec", "builtin"}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_ALWAYS_DANGEROUS = {
    "sudo", "doas", "su", "dd", "shutdown", "reboot", "poweroff",
    "curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "netcat",
    "apt", "apt-get",
}
# Committing, pushing and opening pull requests (gh) are part of the intended
# workflow; only commands that discard work or rewrite history are flagged.
_GIT_DANGEROUS = {"clean", "clone", "fetch", "pull", "stash", "restore", "rebase"}
_FORCE_PUSH = {"-f", "--force", "--force-with-lease", "--force-if-includes",
               "--mirror", "-d", "--delete", "--prune"}
_GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_SAFE_DEVICES = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"}


def _split_lines(command: str) -> str:
    """Replace unquoted newlines with ';' so shlex sees separate commands."""
    out, quote, escape = [], None, False
    for ch in command:
        if escape:
            escape = False
            # a backslash-newline is a line continuation
            out.append(" " if ch == "\n" else ch)
            if ch == "\n":
                out.pop(-2)
            continue
        if ch == "\\" and quote != "'":
            escape = True
        elif quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            ch = ";"
        out.append(ch)
    return "".join(out)


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(_split_lines(command), posix=True, punctuation_chars=True)
    lexer.wordchars += "~$%+,@^{}[]:!#"
    lexer.commenters = ""
    return list(lexer)


def _segments(tokens):
    segment = []
    for token in tokens:
        if token in _OPERATORS:
            if segment:
                yield segment
            segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def _outside(word: str, root: Path) -> bool:
    if word in _SAFE_DEVICES:
        return False
    looks_like_path = word.startswith("/") or ".." in Path(word).parts
    if not looks_like_path:
        return False
    target = Path(os.path.realpath(root / word))
    return target != root and root not in target.parents


def _is_redirect(token: str) -> bool:
    return bool(re.fullmatch(r"\d*(>|>>|>\||&>|>&)", token))


_MESSAGE_FLAGS = {"-m", "--message", "-t", "--title", "-b", "--body"}


def _is_message(words: list[str], i: int) -> bool:
    """Commit messages and PR titles/bodies are text, not paths."""
    if not any(os.path.basename(w) in {"git", "gh"} for w in words[:i]):
        return False
    if words[i - 1] in _MESSAGE_FLAGS:
        return True
    flag, eq, _ = words[i].partition("=")
    return bool(eq) and flag in {"--message", "--title", "--body"}


def _segment_dangerous(words: list[str], root: Path) -> str | None:
    # Redirect targets and path arguments
    for i, word in enumerate(words):
        if _is_message(words, i):
            continue
        if _is_redirect(word) and i + 1 < len(words):
            target = words[i + 1]
            if target.startswith("/dev/") and target not in _SAFE_DEVICES:
                return f"redirect to {target}"
        if re.search(r"(^|[=:])~", word) or "$HOME" in word or "${HOME}" in word:
            return "refers to the home directory"
        candidates = [word]
        if word.startswith("-") and "=" in word:
            candidates.append(word.split("=", 1)[1])
        if any(_outside(c, root) for c in candidates):
            return f"path outside the project root: {word}"

    words = [w for i, w in enumerate(words)
             if not _is_redirect(w) and not (i and _is_redirect(words[i - 1]))]
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    while words and os.path.basename(words[0]) in _WRAPPERS:
        words = words[1:]
        while words and (words[0].startswith("-")
                         or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0])):
            words = words[1:]
    if not words:
        return None

    name = os.path.basename(words[0])
    args = words[1:]

    if name in _ALWAYS_DANGEROUS or name.startswith("mkfs"):
        return name
    if name in _SHELLS and "-c" in args:
        idx = args.index("-c")
        if idx + 1 < len(args):
            return dangerous_reason(args[idx + 1], root)
    if name == "rm":
        for arg in args:
            if arg in {"--recursive", "--force"}:
                return f"rm {arg}"
            if re.fullmatch(r"-[A-Za-z]*[rRf][A-Za-z]*", arg):
                return f"rm {arg}"
        return None
    if name == "find":
        if "-delete" in args:
            return "find -delete"
        for flag in ("-exec", "-execdir", "-ok", "-okdir"):
            if flag in args:
                reason = _segment_dangerous(args[args.index(flag) + 1:], root)
                if reason:
                    return reason
        return None
    if name == "xargs":
        rest = list(args)
        while rest and rest[0].startswith("-"):
            rest = rest[1:]
        return _segment_dangerous(rest, root) if rest else None
    if name == "git":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in _GIT_OPTS_WITH_VALUE else 1
        if i >= len(args):
            return None
        sub, rest = args[i], args[i + 1:]
        if sub in _GIT_DANGEROUS:
            return f"git {sub}"
        if sub == "reset" and "--hard" in rest:
            return "git reset --hard"
        if sub == "push":
            for arg in rest:
                if arg.split("=", 1)[0] in _FORCE_PUSH or arg.startswith("+"):
                    return f"git push {arg}"
            return None
        if sub == "checkout" and "--" in rest:
            return "git checkout --"
        return None
    if name in {"pip", "pip3"} and "install" in args:
        return "pip install"
    if name == "uv" and args[:2] == ["pip", "install"]:
        return "uv pip install"
    if name.startswith("python") and "-m" in args:
        idx = args.index("-m")
        if args[idx + 1:idx + 2] == ["pip"] and "install" in args:
            return "pip install"
    if name in {"npm", "yarn", "pnpm"}:
        positional = [a for a in args if not a.startswith("-")]
        if positional and positional[0] in {"install", "i", "add"}:
            return f"{name} {positional[0]}"
    return None


def dangerous_reason(command: str, root) -> str | None:
    """Return why a shell command is flagged as dangerous, or None.

    A safety net based on the parsed command, not a guarantee.
    """
    root = Path(root).resolve()
    try:
        tokens = _tokens(command)
    except ValueError as exc:
        return f"cannot parse command ({exc})"
    for segment in _segments(tokens):
        reason = _segment_dangerous(segment, root)
        if reason:
            return reason
    return None


def is_dangerous(command: str, root) -> bool:
    return dangerous_reason(command, root) is not None
