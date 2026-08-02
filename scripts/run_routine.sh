#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Navigate to the project root (one level up from scripts/)
cd "$SCRIPT_DIR/.."

# Determine the correct Python executable path
if [ -f ".venv/bin/python" ]; then
    PYTHON_EXEC=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    PYTHON_EXEC="venv/bin/python"
else
    echo "Virtual environment Python executable not found. Please create one named .venv or venv."
    exit 1
fi

# Run the scraper
echo "Starting routine scraper..."

# Check if xvfb-run is available for headless execution
if command -v xvfb-run >/dev/null 2>&1; then
    echo "Executing via xvfb-run (headless mode)..."
    xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" "$PYTHON_EXEC" routine_scrapper.py
else
    echo "xvfb-run not found. Executing in standard mode..."
    "$PYTHON_EXEC" routine_scrapper.py
fi

# If the scraper succeeds, run the formatter
if [ $? -eq 0 ]; then
    echo "Scraper finished. Starting gsheet formatter..."
    "$PYTHON_EXEC" gsheet_formatter.py
else
    echo "Scraper failed. Skipping formatter."
    exit 1
fi