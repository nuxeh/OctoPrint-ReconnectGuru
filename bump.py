import argparse
import re
import os
import subprocess

# Configuration
VERSION_FILE = "VERSION"
TARGET_FILES = [
    VERSION_FILE,
    "octoprint_reconnectguru/__init__.py",
    "setup.py"
]

def get_current_version():
    if not os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, "w") as f: f.write("0.0.0")
        return "0.0.0"
    with open(VERSION_FILE, "r") as f:
        return f.read().strip()

def bump_version(current, part):
    major, minor, patch = map(int, current.split('.'))
    if part == "major": major, minor, patch = major + 1, 0, 0
    elif part == "minor": minor, patch = minor + 1, 0
    else: patch += 1
    return f"{major}.{minor}.{patch}"

def update_files(old_v, new_v):
    # Regex to catch version, __version__, and __plugin_version__
    pattern = re.compile(
        rf'((?:version|__version__|__plugin_version__)\s*=\s*)(["\']){re.escape(old_v)}(["\'])'
    )

    for file_path in TARGET_FILES:
        if not os.path.exists(file_path): continue

        if file_path == VERSION_FILE:
            new_content = new_v
        else:
            with open(file_path, "r") as f: content = f.read()
            new_content = pattern.sub(rf'\g<1>\g<2>{new_v}\g<3>', content)

        with open(file_path, "w") as f:
            f.write(new_content)

def git_commit_prompt(old_v, new_v):
    """Stages files and opens the editor with a pre-filled commit message."""
    try:
        # 1. Stage the modified files
        subprocess.run(["git", "add"] + TARGET_FILES, check=True)

        # 2. Prepare the pre-filled message
        commit_msg = f"Bump {old_v} -> {new_v}\n\n- Updated {', '.join(TARGET_FILES)}"

        # 3. Call git commit with -e to open the editor
        # The editor will show the message and allow the user to edit or abort (by clearing the message)
        subprocess.run(["git", "commit", "-e", "-m", commit_msg], check=True)
        print("✅ Git commit successful.")
    except subprocess.CalledProcessError:
        print("⚠️ Git command failed or commit was aborted by user.")

def main():
    parser = argparse.ArgumentParser(description="Bump version and stage for Git.")
    parser.add_argument("type", choices=["major", "minor", "patch"], nargs="?", default="patch")
    args = parser.parse_args()

    old_v = get_current_version()
    new_v = bump_version(old_v, args.type)

    update_files(old_v, new_v)
    print(f"Bumped version: {old_v} -> {new_v}")

    # Trigger Git staging and editor
    git_commit_prompt(old_v, new_v)

if __name__ == "__main__":
    main()
