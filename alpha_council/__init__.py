"""AlphaCouncil package."""

import os

from dotenv import load_dotenv

explicit_env_file = (os.getenv("ALPHACOUNCIL_ENV_FILE") or "").strip()
if explicit_env_file:
    explicit_env_file = os.path.expandvars(os.path.expanduser(explicit_env_file))
    load_dotenv(explicit_env_file, override=False)

load_dotenv(override=False)
