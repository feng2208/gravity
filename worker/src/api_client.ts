import { TokenManager } from './token_manager';

const API_URL = 'https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:streamGenerateContent?alt=sse';
const MODELS_URL = 'https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:fetchAvailableModels';
const HOST = 'daily-cloudcode-pa.sandbox.googleapis.com';
const USER_AGENT = 'antigravity/1.11.3 windows/amd64';

export class ApiClient {
    private tokenManager: TokenManager;

    constructor(tokenManager: TokenManager) {
        this.tokenManager = tokenManager;
    }

    async getAvailableModels() {
        const token = await this.tokenManager.getToken();
        if (!token || !token.access_token) {
            throw new Error('No available token');
        }

        const response = await fetch(MODELS_URL, {
            method: 'POST',
            headers: {
                'Host': HOST,
                'User-Agent': USER_AGENT,
                'Authorization': `Bearer ${token.access_token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({}),
        });

        if (!response.ok) {
            throw new Error(`Failed to get models: ${response.statusText}`);
        }

        const data: any = await response.json();
        //console.log('getAvailableModels response:', JSON.stringify(data, null, 2));

        if (data.error) {
            throw new Error(`Upstream API Error: ${JSON.stringify(data.error)}`);
        }

        // Python code uses: for model_id in data.get('models', {})
        // If models is an object/dict, iterate over keys; if array, use as-is
        const models = data.models || {};
        const modelIds = Array.isArray(models) ? models : Object.keys(models);

        return {
            object: 'list',
            data: modelIds.map((modelId: string) => ({
                id: modelId,
                object: 'model',
                created: Math.floor(Date.now() / 1000),
                owned_by: 'google',
            })),
        };
    }

    async *generateAssistantResponse(requestBody: any) {
        const token = await this.tokenManager.getToken();
        if (!token || !token.access_token) {
            throw new Error('No available token');
        }

        const response = await fetch(API_URL, {
            method: 'POST',
            headers: {
                'Host': HOST,
                'User-Agent': USER_AGENT,
                'Authorization': `Bearer ${token.access_token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`API request failed (${response.status}): ${errorText}`);
        }

        if (!response.body) throw new Error('Response body is null');

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        let thinkingStarted = false;
        let toolCalls: any[] = [];

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const jsonStr = line.slice(6);
                if (jsonStr === '[DONE]') return;

                try {
                    const data = JSON.parse(jsonStr);
                    const candidates = data.response?.candidates || [{}];
                    const parts = candidates[0]?.content?.parts || [];

                    if (parts.length > 0) {
                        for (const part of parts) {
                            if (part.thought === true) {
                                if (!thinkingStarted) {
                                    yield { type: 'thinking', content: '<think>\n' };
                                    thinkingStarted = true;
                                }
                                yield { type: 'thinking', content: part.text || '' };
                            } else if (part.text !== undefined) {
                                if (thinkingStarted) {
                                    yield { type: 'thinking', content: '\n</think>\n' };
                                    thinkingStarted = false;
                                }
                                yield { type: 'text', content: part.text };
                            } else if (part.functionCall) {
                                const fc = part.functionCall;
                                toolCalls.push({
                                    id: fc.id,
                                    type: 'function',
                                    function: {
                                        name: fc.name,
                                        arguments: JSON.stringify(fc.args || {})
                                    }
                                });
                            }
                        }
                    }

                    const finishReason = candidates[0]?.finishReason;
                    if (finishReason && toolCalls.length > 0) {
                        if (thinkingStarted) {
                            yield { type: 'thinking', content: '\n</think>\n' };
                            thinkingStarted = false;
                        }
                        yield { type: 'tool_calls', tool_calls: toolCalls };
                        toolCalls = [];
                    }

                } catch (e) {
                    console.warn('Error parsing JSON line:', e);
                }
            }
        }
    }
}
