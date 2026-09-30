"""Deterministic engine-import settings, independent of a developer's .env."""
import os

_configured = False


def configure():
    global _configured
    if _configured:
        return
    _configured = True
    os.environ.update({
        'DAZEDTL_TEST_OFFLINE': '1', 'PYTHON_DOTENV_DISABLED': '1',
        'model': 'gpt-4o-mini', 'language': 'English', 'timeout': '5',
        'width': '60', 'faceWidth': '50', 'listWidth': '80', 'noteWidth': '80',
        'key': 'offline-test-key', 'api': 'https://api.openai.com/v1',
        'API_PROVIDER': 'openai', 'organization': '',
    })
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY', 'GEMINI_API_KEY',
                 'MISTRAL_API_KEY', 'DAZED_GAME_ROOT', 'DAZED_GLOSSARY_PATH'):
        os.environ.pop(name, None)
