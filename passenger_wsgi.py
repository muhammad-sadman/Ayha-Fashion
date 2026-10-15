"""Entry point for cPanel "Setup Python App" (Passenger) hosting. Not used anywhere else."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ayha_project.settings")

from ayha_project.wsgi import application  # noqa: E402,F401
