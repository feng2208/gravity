import { ChatMessage, Account } from './types';

const CONFIG = {
    defaults: {
        top_p: 0.95,
        top_k: 40,
        temperature: 0.7,
        max_tokens: 2048,
    },
    system_instruction: "You are a helpful, respectful and honest assistant. Always answer as helpfully as possible, while being safe. Your answers should not include any harmful, unethical, racist, sexist, toxic, dangerous, or illegal content. Please ensure that your responses are socially unbiased and positive in nature.\n\nIf a question does not make any sense, or is not factually coherent, explain why instead of answering something not correct. If you don't know the answer to a question, please don't share false information."
};

function generateRequestId(): string {
    return `req_${crypto.randomUUID().replace(/-/g, '')}`;
}

function extractImagesFromContent(content: any): { text: string; images: any[] } {
    const result: { text: string; images: any[] } = { text: '', images: [] };
    if (typeof content === 'string') {
        result.text = content;
        return result;
    }

    if (Array.isArray(content)) {
        for (const item of content) {
            if (item.type === 'text') {
                result.text += item.text || '';
            } else if (item.type === 'image_url') {
                const imageUrl = item.image_url?.url || '';
                const match = imageUrl.match(/^data:image\/(\w+);base64,(.+)$/);
                if (match) {
                    const imgFormat = match[1];
                    const base64Data = match[2];
                    result.images.push({
                        inlineData: {
                            mimeType: `image/${imgFormat}`,
                            data: base64Data
                        }
                    });
                }
            }
        }
    }
    return result;
}

function handleUserMessage(extracted: { text: string; images: any[] }, antigravityMessages: any[]) {
    const parts: any[] = [{ text: extracted.text }];
    if (extracted.images.length > 0) {
        parts.push(...extracted.images);
    }
    antigravityMessages.push({ role: 'user', parts });
}

function handleAssistantMessage(message: any, antigravityMessages: any[]) {
    const hasToolCalls = !!message.tool_calls;
    const hasContent = !!(message.content && message.content.trim());

    const antigravityTools: any[] = [];
    if (hasToolCalls) {
        for (const toolCall of message.tool_calls) {
            let args = {};
            try {
                args = JSON.parse(toolCall.function.arguments);
            } catch (e) {
                args = { query: toolCall.function.arguments };
            }

            antigravityTools.push({
                functionCall: {
                    id: toolCall.id,
                    name: toolCall.function.name,
                    args: args
                }
            });
        }
    }

    const lastMessage = antigravityMessages.length > 0 ? antigravityMessages[antigravityMessages.length - 1] : null;

    if (lastMessage && lastMessage.role === 'model' && hasToolCalls && !hasContent) {
        lastMessage.parts.push(...antigravityTools);
    } else {
        const parts: any[] = [];
        if (hasContent) {
            parts.push({ text: message.content });
        }
        if (antigravityTools.length > 0) {
            parts.push(...antigravityTools);
        }

        if (parts.length > 0) {
            antigravityMessages.push({ role: 'model', parts });
        }
    }
}

function handleToolCall(message: any, antigravityMessages: any[]) {
    let functionName = '';
    // Find the original function call
    for (let i = antigravityMessages.length - 1; i >= 0; i--) {
        if (antigravityMessages[i].role === 'model') {
            for (const part of antigravityMessages[i].parts || []) {
                if (part.functionCall && part.functionCall.id === message.tool_call_id) {
                    functionName = part.functionCall.name;
                    break;
                }
            }
            if (functionName) break;
        }
    }

    const functionResponse = {
        functionResponse: {
            id: message.tool_call_id,
            name: functionName,
            response: { output: message.content }
        }
    };

    const lastMessage = antigravityMessages.length > 0 ? antigravityMessages[antigravityMessages.length - 1] : null;

    if (
        lastMessage &&
        lastMessage.role === 'user' &&
        lastMessage.parts.some((p: any) => 'functionResponse' in p)
    ) {
        lastMessage.parts.push(functionResponse);
    } else {
        antigravityMessages.push({ role: 'user', parts: [functionResponse] });
    }
}

function openaiMessageToAntigravity(openaiMessages: ChatMessage[]): any[] {
    const antigravityMessages: any[] = [];
    for (const message of openaiMessages) {
        const role = message.role;
        if (role === 'user' || role === 'system') {
            const extracted = extractImagesFromContent(message.content || '');
            handleUserMessage(extracted, antigravityMessages);
        } else if (role === 'assistant') {
            handleAssistantMessage(message, antigravityMessages);
        } else if (role === 'tool') {
            handleToolCall(message, antigravityMessages);
        }
    }
    return antigravityMessages;
}

function generateGenerationConfig(parameters: any, enableThinking: boolean, actualModelName: string) {
    const generationConfig: any = {
        topP: parameters.top_p ?? CONFIG.defaults.top_p,
        topK: parameters.top_k ?? CONFIG.defaults.top_k,
        temperature: parameters.temperature ?? CONFIG.defaults.temperature,
        candidateCount: 1,
        maxOutputTokens: parameters.max_tokens ?? CONFIG.defaults.max_tokens,
        stopSequences: [
            "<|user|>", "<|bot|>", "<|context_request|>",
            "<|endoftext|>", "<|end_of_turn|>"
        ],
        thinkingConfig: {
            includeThoughts: enableThinking,
            thinkingBudget: enableThinking ? 1024 : 0
        }
    };

    if (enableThinking && actualModelName.includes('claude')) {
        delete generationConfig.topP;
    }
    return generationConfig;
}

function convertOpenAiToolsToAntigravity(openaiTools?: any[]) {
    if (!openaiTools) return [];

    return openaiTools.map(tool => {
        const funcParams = JSON.parse(JSON.stringify(tool.function.parameters || {}));
        if (funcParams.$schema) {
            delete funcParams.$schema;
        }

        return {
            functionDeclarations: [{
                name: tool.function.name,
                description: tool.function.description,
                parameters: funcParams
            }]
        };
    });
}

export function generateRequestBody(
    token: Account,
    messages: ChatMessage[],
    model: string,
    params: any,
    tools?: any[]
): any {
    const enableThinking = (
        model.endsWith('-thinking') ||
        model === 'gemini-2.5-pro' ||
        model.startsWith('gemini-3-pro-') ||
        ['rev19-uic3-1p', 'gpt-oss-120b-medium'].includes(model)
    );

    const actualModelName = model.endsWith('-thinking') ? model.slice(0, -9) : model;

    const body: any = {
        requestId: generateRequestId(),
        request: {
            contents: openaiMessageToAntigravity(messages),
            systemInstruction: {
                role: 'user',
                parts: [{ text: CONFIG.system_instruction }]
            },
            generationConfig: generateGenerationConfig(params, enableThinking, actualModelName),
        },
        model: actualModelName,
        userAgent: 'antigravity'
    };

    // Only add tools and toolConfig if tools are provided
    if (tools && tools.length > 0) {
        body.request.tools = convertOpenAiToolsToAntigravity(tools);
        body.request.toolConfig = {
            functionCallingConfig: { mode: 'ANY' }
        };
    }

    if (token.projectId) {
        body.project = token.projectId;
    }
    if (token.sessionId) {
        body.request.sessionId = token.sessionId;
    }

    return body;
}
