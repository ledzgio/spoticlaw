#!/bin/bash
# Spoticlaw Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/ledzgio/spoticlaw/main/install.sh | bash

set -e

echo "🎵 Installing Spoticlaw..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+ first."
    exit 1
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Create venv
echo "📦 Creating virtual environment..."
python3 -m venv "$SCRIPT_DIR/.venv"

# Activate venv
source "$SCRIPT_DIR/.venv/bin/activate"

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q requests python-dotenv

# Check for .env
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    if [ -f "$SCRIPT_DIR/.env.example" ]; then
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        echo "✅ Created .env file"
        echo ""
        echo "⚠️  IMPORTANT: Edit .env and add your Spotify credentials:"
        echo "   SPOTIFY_CLIENT_ID=your_client_id"
        echo "   SPOTIFY_CLIENT_SECRET=your_client_secret"
        echo ""
        echo "   Get credentials at: https://developer.spotify.com/dashboard"
    fi
fi

# Check for token
if [ ! -f "$SCRIPT_DIR/.spotify_cache" ]; then
    echo ""
    echo "⚠️  No token found. To authenticate:"
    echo "   1. Edit .env with your Spotify credentials"
    echo "   2. Run: python scripts/auth.py"
    echo "   3. Open the URL and authorize"
    echo "   4. Copy .spotify_cache to this folder"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "To authenticate (first time only):"
echo "  1. Edit .env with Spotify credentials"
echo "  2. python scripts/auth.py"
echo "  3. Open the URL in browser"
echo "  4. Copy .spotify_cache to this folder"
echo ""
echo "Usage:"
echo "  source .venv/bin/activate"
echo "  python -c 'from spoticlaw import player; ...'"
