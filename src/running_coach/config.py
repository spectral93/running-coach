"""Settings, read from config/coach.yaml with environment-variable overrides."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

DEFAULT_CONFIG_PATH = Path("config/coach.yaml")


class Settings(BaseModel):
    # Any pydantic-ai "provider:model" string, e.g. "anthropic:claude-sonnet-5",
    # "openai:gpt-5", "google-gla:gemini-2.5-pro", or "ollama:llama3.3".
    model: str = "anthropic:claude-sonnet-5"
    data_dir: Path = Path("data")


def load_settings(config_path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    load_dotenv()
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    values: dict = {}
    if config_path.exists():
        values = yaml.safe_load(config_path.read_text()) or {}
    if model := os.getenv("COACH_MODEL"):
        values["model"] = model
    if data_dir := os.getenv("COACH_DATA_DIR"):
        values["data_dir"] = data_dir
    return Settings.model_validate(values)
