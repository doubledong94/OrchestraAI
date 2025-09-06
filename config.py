import os
from typing import Dict, Any

class Config:
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
    
    OUTPUT_DIR = os.getenv("OUTPUT_DIR", "generated_code")
    
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
    
    MAX_MESSAGES_HISTORY = int(os.getenv("MAX_MESSAGES_HISTORY", "1000"))
    
    @classmethod
    def get_ollama_params(cls) -> Dict[str, Any]:
        return {
            "model": cls.OLLAMA_MODEL,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "top_k": 40,
            }
        }