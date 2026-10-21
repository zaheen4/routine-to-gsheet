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
echo "Starting routine scraper (official class routine report)..."

# On Linux the pipeline runs on a virtual X display (xvfb-run): true headless
# Chrome gets challenged by Cloudflare, and a headed Chrome without a display
# server crashes immediately. Fail fast with an actionable message when
# xvfb-run is missing rather than falling back to a broken run.
if [ "$(uname -s)" = "Linux" ]; then
    if command -v xvfb-run >/dev/null 2>&1; then
        echo "Executing via xvfb-run (virtual display)..."
        xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" \
            "$PYTHON_EXEC" extract_ucam.py --output output/routine_data.json
    else
        echo "ERROR: xvfb-run is not installed, but the Linux pipeline requires a virtual X display."
        echo "Install it with your package manager, for example:"
        echo "  Debian/Ubuntu:  sudo apt install xvfb"
        echo "  Fedora/RHEL:    sudo dnf install xorg-x11-server-Xvfb"
        echo "  Arch:           sudo pacman -S xorg-server-xvfb"
        exit 1
    fi
else
    echo "Executing on non-Linux platform (no xvfb-run needed)..."
    "$PYTHON_EXEC" extract_ucam.py --output output/routine_data.json
fi

# If the scraper succeeds, run the formatter and then the calendar exporter.
if [ $? -eq 0 ]; then
    echo "Scraper finished. Starting gsheet formatter..."
    "$PYTHON_EXEC" gsheet_formatter.py --data output/routine_data.json
    # Propagate the formatter's status: a non-zero exit means the spreadsheet
    # was NOT updated (bad/absent data, auth failure, or a write failure), which
    # must not look like a successful run.
    if [ $? -ne 0 ]; then
        echo "Formatter failed. Spreadsheet not updated."
        exit 1
    fi

    echo "Formatter finished. Writing calendar file..."
    "$PYTHON_EXEC" ics_exporter.py --data output/routine_data.json --output output/routine.ics
    if [ $? -ne 0 ]; then
        echo "Calendar export failed."
        exit 1
    fi
else
    echo "Scraper failed. Skipping formatter and calendar export."
    exit 1
fi
