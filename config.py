import os

class ServerConfig:
    """Configuration class for the server."""
    HOST = "0.0.0.0"
    PORT = 3001
    # IMPORTANT: Set a secure API key in a real environment
    # You can set it as an environment variable: export API_KEY='your-real-api-key'
    API_KEY = os.environ.get("API_KEY", "your-secret-api-key")

class ApiClientConfig:
    """Configuration for the API client."""
    API_URL = 'https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:streamGenerateContent?alt=sse'
    MODELS_URL = 'https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:fetchAvailableModels'
    HOST = 'daily-cloudcode-pa.sandbox.googleapis.com'
    USER_AGENT = 'antigravity/1.11.3 windows/amd64'

CONFIG = ServerConfig()
API_CLIENT_CONFIG = ApiClientConfig()