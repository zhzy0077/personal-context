#!/usr/bin/env python3
"""Personal Context Store - Setup Script for Claude/OpenCode MCP configuration."""

import json
import os
import shutil
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
ENV_FILE = REPO_DIR / ".env"


def read_env():
    """Read .env file and return settings."""
    settings = {
        "auth_enabled": False,
        "auth_username": "",
        "auth_password": "",
        "server_url": "http://127.0.0.1:8000",
    }

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key == "PERSONAL_CONTEXT_HTTP_AUTH_USERNAME":
                    settings["auth_username"] = value
                elif key == "PERSONAL_CONTEXT_HTTP_AUTH_PASSWORD":
                    settings["auth_password"] = value
                elif key == "PERSONAL_CONTEXT_SERVER_URL":
                    settings["server_url"] = value

        if settings["auth_username"] and settings["auth_password"]:
            settings["auth_enabled"] = True

    return settings


def generate_auth_header(username, password):
    """Generate base64 auth header."""
    import base64
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


def setup_opencode_agents():
    """Setup OpenCode AGENTS.md for session rules."""
    opencode_dir = Path.home() / ".config" / "opencode"
    agents_file = opencode_dir / "AGENTS.md"

    opencode_dir.mkdir(parents=True, exist_ok=True)

    agents_content = """# OpenCode Session Rules

## Initialization
- You MUST call the tool `load-personal-prompts` immediately at the start of every session.
- Do NOT address the user's first query until you have successfully called this tool and received its output.
- The output of this tool contains critical context and rules for this session.
"""
    agents_file.write_text(agents_content)
    print(f"  Created: {agents_file}")


def setup_claude_desktop(settings):
    """Setup Claude Desktop MCP configuration."""
    claude_dir = Path.home() / "Library" / "Application Support" / "Claude"
    config_file = claude_dir / "claude_desktop_config.json"

    claude_dir.mkdir(parents=True, exist_ok=True)

    if config_file.exists():
        print(f"  Backing up existing config to {config_file}.bak")
        shutil.copy(config_file, f"{config_file}.bak")
        with open(config_file) as f:
            config = json.load(f)
    else:
        config = {"mcpServers": {}}

    mcp_config = {
        "type": "http",
        "url": f"{settings['server_url']}/mcp",
    }

    if settings["auth_enabled"]:
        mcp_config["headers"] = {
            "Authorization": generate_auth_header(
                settings["auth_username"], settings["auth_password"]
            )
        }

    config["mcpServers"]["personal-context"] = mcp_config

    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)

    print(f"  Created: {config_file}")


def setup_opencode_mcp(settings):
    """Setup OpenCode MCP configuration."""
    opencode_dir = Path.home() / ".config" / "opencode"
    config_file = opencode_dir / "opencode.json"

    opencode_dir.mkdir(parents=True, exist_ok=True)

    mcp_config = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "personal-context": {
                "type": "remote",
                "url": f"{settings['server_url']}/mcp",
            }
        }
    }

    if settings["auth_enabled"]:
        mcp_config["mcp"]["personal-context"]["headers"] = {
            "Authorization": generate_auth_header(
                settings["auth_username"], settings["auth_password"]
            )
        }

    with open(config_file, "w") as f:
        json.dump(mcp_config, f, indent=2)

    print(f"  Created: {config_file}")


def setup_global_claude_md():
    """Setup global CLAUDE.md for Claude Code."""
    claude_dir = Path.home() / ".claude"
    claude_file = claude_dir / "CLAUDE.md"

    claude_dir.mkdir(parents=True, exist_ok=True)

    session_rules = """
# Session Rules

## Initialization
- You MUST call the tool `load-personal-prompts` immediately at the start of every session.
- Do NOT address the user's first query until you have successfully called this tool and received its output.
- The output of this tool contains critical context and rules for this session.
"""

    if claude_file.exists():
        content = claude_file.read_text()
        if "load-personal-prompts" not in content:
            claude_file.write_text(content + session_rules)
            print(f"  Appended session rules to: {claude_file}")
        else:
            print(f"  Session rules already present in: {claude_file}")
    else:
        claude_file.write_text(session_rules.lstrip())
        print(f"  Created: {claude_file}")


def main():
    print("Personal Context Store - Setup Script")
    print("=" * 40)
    print()

    settings = read_env()

    print(f"Server URL: {settings['server_url']}")
    print(f"Authentication: {'ENABLED' if settings['auth_enabled'] else 'DISABLED'}")
    print()

    print("Setting up OpenCode AGENTS.md...")
    setup_opencode_agents()
    print()

    print("Setting up Claude Desktop MCP configuration...")
    setup_claude_desktop(settings)
    print()

    print("Setting up OpenCode MCP configuration...")
    setup_opencode_mcp(settings)
    print()

    print("Setting up global CLAUDE.md...")
    setup_global_claude_md()
    print()

    print("=" * 40)
    print("Setup Complete!")
    print("=" * 40)
    print()
    print("Next steps:")
    print("  1. Start the MCP server: cd", REPO_DIR, "&& uv run main.py")
    print("  2. Restart Claude Desktop / OpenCode")
    print("  3. The MCP server should auto-connect")


if __name__ == "__main__":
    main()
