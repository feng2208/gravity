import json
import logging
import httpx  # Using httpx for asynchronous requests
import time

try:
    from .token_manager import TokenManager
except ImportError:
    from token_manager import TokenManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from config import API_CLIENT_CONFIG

class ApiClient:
    """
    Asynchronous client for the generative language API using httpx.
    """

    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
        # Create a single httpx.AsyncClient instance for reuse
        self.http_client = httpx.AsyncClient(timeout=300.0)

    async def generate_assistant_response(self, request_body):
        """
        Sends a request to the model and yields streaming response chunks asynchronously.
        This is an async generator.
        """
        token = self.token_manager.get_token()
        if not token:
            raise ConnectionError('No available token. Please run oauth_client.py to authenticate.')

        headers = {
            'Host': API_CLIENT_CONFIG.HOST,
            'User-Agent': API_CLIENT_CONFIG.USER_AGENT,
            'Authorization': f"Bearer {token['access_token']}",
            'Content-Type': 'application/json',
            'Accept-Encoding': 'gzip',
        }
        
        try:
            async with self.http_client.stream(
                "POST",
                API_CLIENT_CONFIG.API_URL,
                headers=headers,
                json=request_body
            ) as response:
                # Handle non-successful responses
                if response.status_code != 200:
                    error_text = await response.aread()
                    if response.status_code == 403:
                        raise PermissionError(f"Account lacks permission. Details: {error_text.decode()}")
                    raise ConnectionError(f"API request failed ({response.status_code}): {error_text.decode()}")

                thinking_started = False
                tool_calls = []

                # Asynchronously iterate over the streaming response lines
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):
                        continue

                    json_str = line[6:]
                    try:
                        data = json.loads(json_str)
                        candidates = data.get('response', {}).get('candidates', [{}])
                        parts = candidates[0].get('content', {}).get('parts', [])
                        
                        if parts:
                            for part in parts:
                                if part.get('thought') is True:
                                    if not thinking_started:
                                        yield {'type': 'thinking', 'content': '<think>\n'}
                                        thinking_started = True
                                    yield {'type': 'thinking', 'content': part.get('text', '')}
                                elif 'text' in part:
                                    if thinking_started:
                                        yield {'type': 'thinking', 'content': '\n</think>\n'}
                                        thinking_started = False
                                    yield {'type': 'text', 'content': part['text']}
                                elif 'functionCall' in part:
                                    fc = part['functionCall']
                                    tool_calls.append({
                                        'id': fc.get('id'),
                                        'type': 'function',
                                        'function': {
                                            'name': fc.get('name'),
                                            'arguments': json.dumps(fc.get('args', {}))
                                        }
                                    })

                        finish_reason = candidates[0].get('finishReason')
                        if finish_reason and tool_calls:
                            if thinking_started:
                                yield {'type': 'thinking', 'content': '\n</think>\n'}
                                thinking_started = False
                            yield {'type': 'tool_calls', 'tool_calls': tool_calls}
                            tool_calls = []

                    except json.JSONDecodeError:
                        logging.warning(f"Ignoring JSON parse error for line: {json_str}")
                        continue
        
        except httpx.RequestError as e:
            raise ConnectionError(f"An error occurred during the API request: {e}")

    async def get_available_models(self):
        """Asynchronously retrieves a list of available models."""
        token = self.token_manager.get_token()
        if not token:
            raise ConnectionError('No available token. Please run oauth_client.py to authenticate.')

        headers = {
            'Host': API_CLIENT_CONFIG.HOST,
            'User-Agent': API_CLIENT_CONFIG.USER_AGENT,
            'Authorization': f"Bearer {token['access_token']}",
            'Content-Type': 'application/json',
        }
        
        try:
            response = await self.http_client.post(API_CLIENT_CONFIG.MODELS_URL, headers=headers, json={})
            response.raise_for_status()
            data = response.json()
            
            return {
                'object': 'list',
                'data': [
                    {
                        'id': model_id,
                        'object': 'model',
                        'created': int(time.time()),
                        'owned_by': 'google'
                    }
                    for model_id in data.get('models', {})
                ]
            }
        except httpx.RequestError as e:
            raise ConnectionError(f"Failed to get available models: {e}")

    async def close(self):
        """Closes the httpx client. Should be called on application shutdown."""
        await self.http_client.aclose()
