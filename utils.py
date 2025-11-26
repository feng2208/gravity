import re
import uuid
import json

# This is a Python representation of the config object from the original JS file.
# In a real application, this might be loaded from a file or environment variables.
class Config:
    def __init__(self):
        self.defaults = {
            'top_p': 0.95,
            'top_k': 40,
            'temperature': 0.7,
            'max_tokens': 2048,
        }
        self.system_instruction = (
            "You are a helpful, respectful and honest assistant. "
            "Always answer as helpfully as possible, while being safe. "
            "Your answers should not include any harmful, unethical, racist, sexist, "
            "toxic, dangerous, or illegal content. Please ensure that your responses "
            "are socially unbiased and positive in nature.\n\n"
            "If a question does not make any sense, or is not factually coherent, "
            "explain why instead of answering something not correct. If you don't know "
            "the answer to a question, please don't share false information."
        )

CONFIG = Config()


def generate_request_id():
    """Generates a unique request ID."""
    return f"req_{{uuid.uuid4().hex}}"


def extract_images_from_content(content):
    """Extracts text and base64 encoded images from multimodal content."""
    result = {'text': '', 'images': []}
    if isinstance(content, str):
        result['text'] = content
        return result

    if isinstance(content, list):
        for item in content:
            if item.get('type') == 'text':
                result['text'] += item.get('text', '')
            elif item.get('type') == 'image_url':
                image_url = item.get('image_url', {}).get('url', '')
                # Regex to parse data URI for images
                match = re.match(r'^data:image/(\w+);base64,(.+)$', image_url)
                if match:
                    img_format = match.group(1)
                    base64_data = match.group(2)
                    result['images'].append({
                        'inlineData': {
                            'mimeType': f'image/{img_format}',
                            'data': base64_data
                        }
                    })
    return result


def handle_user_message(extracted, antigravity_messages):
    """Converts a user message to the antigravity format."""
    parts = [{'text': extracted['text']}]
    if extracted['images']:
        parts.extend(extracted['images'])
    antigravity_messages.append({'role': 'user', 'parts': parts})


def handle_assistant_message(message, antigravity_messages):
    """Converts an assistant message (with potential tool calls) to the antigravity format."""
    has_tool_calls = bool(message.get('tool_calls'))
    has_content = bool(message.get('content') and message['content'].strip())

    antigravity_tools = []
    if has_tool_calls:
        for tool_call in message['tool_calls']:
            try:
                # The 'arguments' from OpenAI are a JSON string, so we parse them.
                args = json.loads(tool_call['function']['arguments'])
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, use the raw string as per the JS example's 'query' fallback
                args = {'query': tool_call['function']['arguments']}

            antigravity_tools.append({
                'functionCall': {
                    'id': tool_call['id'],
                    'name': tool_call['function']['name'],
                    'args': args
                }
            })

    last_message = antigravity_messages[-1] if antigravity_messages else None

    # If the last message was a model call and this new one only adds tools, merge them.
    if last_message and last_message.get('role') == 'model' and has_tool_calls and not has_content:
        last_message['parts'].extend(antigravity_tools)
    else:
        parts = []
        if has_content:
            parts.append({'text': message['content']})
        if antigravity_tools:
            parts.extend(antigravity_tools)
        
        if parts:
            antigravity_messages.append({'role': 'model', 'parts': parts})


def handle_tool_call(message, antigravity_messages):
    """Converts a tool response message to the antigravity format."""
    function_name = ''
    # Find the original function call to get its name
    for i in range(len(antigravity_messages) - 1, -1, -1):
        if antigravity_messages[i].get('role') == 'model':
            for part in antigravity_messages[i].get('parts', []):
                if part.get('functionCall') and part['functionCall'].get('id') == message.get('tool_call_id'):
                    function_name = part['functionCall']['name']
                    break
            if function_name:
                break
    
    function_response = {
        'functionResponse': {
            'id': message.get('tool_call_id'),
            'name': function_name,
            'response': {'output': message.get('content')}
        }
    }

    last_message = antigravity_messages[-1] if antigravity_messages else None
    # If the last message was already a tool response, merge them.
    if (
        last_message 
        and last_message.get('role') == 'user' 
        and any('functionResponse' in p for p in last_message.get('parts', []))
    ):
        last_message['parts'].append(function_response)
    else:
        antigravity_messages.append({'role': 'user', 'parts': [function_response]})


def openai_message_to_antigravity(openai_messages):
    """Converts a list of OpenAI messages to the antigravity format."""
    antigravity_messages = []
    for message in openai_messages:
        role = message.get('role')
        if role in ("user", "system"):
            # System messages are treated as user messages
            extracted = extract_images_from_content(message.get('content', ''))
            handle_user_message(extracted, antigravity_messages)
        elif role == "assistant":
            handle_assistant_message(message, antigravity_messages)
        elif role == "tool":
            handle_tool_call(message, antigravity_messages)
    return antigravity_messages


def generate_generation_config(parameters, enable_thinking, actual_model_name):
    """Builds the generationConfig dictionary."""
    generation_config = {
        'topP': parameters.get('top_p', CONFIG.defaults['top_p']),
        'topK': parameters.get('top_k', CONFIG.defaults['top_k']),
        'temperature': parameters.get('temperature', CONFIG.defaults['temperature']),
        'candidateCount': 1,
        'maxOutputTokens': parameters.get('max_tokens', CONFIG.defaults['max_tokens']),
        'stopSequences': [
            "<|user|>", "<|bot|>", "<|context_request|>",
            "<|endoftext|>", "<|end_of_turn|>"
        ],
        'thinkingConfig': {
            'includeThoughts': enable_thinking,
            'thinkingBudget': 1024 if enable_thinking else 0
        }
    }
    if enable_thinking and "claude" in actual_model_name:
        if 'topP' in generation_config:
            del generation_config['topP']
    return generation_config


def convert_openai_tools_to_antigravity(openai_tools):
    """Converts OpenAI tool definitions to the antigravity format."""
    if not openai_tools:
        return []
    
    converted = []
    for tool in openai_tools:
        # Deep copy to avoid modifying the original tool definition
        func_params = json.loads(json.dumps(tool.get('function', {}).get('parameters', {})))
        if '$schema' in func_params:
            del func_params['$schema']
        
        converted.append({
            'functionDeclarations': [{
                'name': tool.get('function', {}).get('name'),
                'description': tool.get('function', {}).get('description'),
                'parameters': func_params
            }]
        })
    return converted


def generate_request_body(token_manager, openai_messages, model_name, parameters, openai_tools):
    """
    The main function to generate the entire antigravity request body.
    """
    token = token_manager.get_token()
    if not token:
        raise ConnectionError('No available token. Please run oauth_client.py to get a token.')

    # Logic to decide if 'thinking' mode should be enabled based on model name
    enable_thinking = (
        model_name.endswith('-thinking') 
        or model_name == 'gemini-2.5-pro'
        or model_name.startswith('gemini-3-pro-')
        or model_name in ("rev19-uic3-1p", "gpt-oss-120b-medium")
    )
    
    actual_model_name = model_name[:-9] if model_name.endswith('-thinking') else model_name

    body = {
        'requestId': generate_request_id(),
        'request': {
            'contents': openai_message_to_antigravity(openai_messages),
            'systemInstruction': {
                'role': 'user',
                'parts': [{'text': CONFIG.system_instruction}]
            },
            'tools': convert_openai_tools_to_antigravity(openai_tools),
            'toolConfig': {
                'functionCallingConfig': {'mode': 'ANY'} # Use ANY to allow model to choose tools
            },
            'generationConfig': generate_generation_config(parameters, enable_thinking, actual_model_name),
        },
        'model': actual_model_name,
        'userAgent': 'antigravity'
    }

    # These fields were in the JS version but depend on custom token properties.
    # Add them only if they exist in the token object.
    if token.get('projectId'):
        body['project'] = token['projectId']
    if token.get('sessionId'):
        body['request']['sessionId'] = token['sessionId']

    return body
