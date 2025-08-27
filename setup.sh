#!/bin/bash

# Setup script for Codex MCP Orchestra
# This script helps configure the system for first-time use

set -e

echo "Codex MCP Orchestra Setup"
echo "========================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "Creating .env from template..."
    cp .env.example .env
    echo "✓ Created .env file"
    echo ""
    echo "IMPORTANT: Edit .env with your configuration:"
    echo "  - Set EMAIL_DOMAIN to your actual domain"
    echo "  - Set SENDER_EMAIL to your email address"
    echo "  - Configure agent home directories"
    echo ""
else
    echo "✓ .env file already exists"
fi

# Check config files
echo ""
echo "Checking configuration files..."

if [ ! -f config/email_security.toml ]; then
    echo "Creating email_security.toml from template..."
    cp config/email_security.example.toml config/email_security.toml
    echo "✓ Created config/email_security.toml"
fi

# Note: routing.toml is tracked in git, so it exists

echo ""
echo "Setting up Python environment..."
if [ ! -d .venv ]; then
    python3 -m venv .venv
    echo "✓ Created virtual environment"
fi

source .venv/bin/activate
pip install -q -r requirements.txt
echo "✓ Installed Python dependencies"

# Check for Codex CLI
echo ""
echo "Checking Codex CLI..."
if command -v codex &> /dev/null; then
    echo "✓ Codex CLI is installed"
else
    echo "✗ Codex CLI not found. Please install from: https://github.com/openai/codex"
    exit 1
fi

# Initialize submodules
echo ""
echo "Initializing submodules..."
git submodule update --init --recursive
echo "✓ Submodules initialized"

# Create required directories
echo ""
echo "Creating required directories..."
mkdir -p logs mcp/logs temp
echo "✓ Directories created"

echo ""
echo "Setup Complete!"
echo "=============="
echo ""
echo "Next steps:"
echo "1. Edit .env with your configuration"
echo "2. Configure Codex agents in their respective directories"
echo "3. Start the system with: ./start-all.sh"
echo ""
echo "For detailed instructions, see README.md and SETUP.md"