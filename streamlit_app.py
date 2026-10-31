"""Run with: .venv/bin/python -m streamlit run streamlit_app.py"""

from pathlib import Path

from shopping_agent.ui import run_app

run_app(Path(__file__).resolve().parent)
