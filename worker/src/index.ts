import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { Env } from './types';
import { TokenManager } from './token_manager';
import { ApiClient } from './api_client';
import { generateRequestBody } from './utils';

const app = new Hono<{ Bindings: Env }>();

app.use('*', cors());

// Middleware for API Key validation
app.use('*', async (c, next) => {
    if (c.req.path === '/' || c.req.path === '/health') {
        return next();
    }

    const apiKey = c.env.API_KEY;
    if (apiKey) {
        const authHeader = c.req.header('Authorization');
        if (!authHeader || authHeader.split(' ')[1] !== apiKey) {
            return c.json({ error: 'Unauthorized', message: 'Invalid or missing API Key' }, 401);
        }
    }
    await next();
});

app.get('/', (c) => c.text('OpenAI Compatible Proxy Worker is running!'));

app.get('/v1/models', async (c) => {
    try {
        const tokenManager = new TokenManager(c.env.ACCOUNTS, c.env.TOKEN_CACHE);
        const apiClient = new ApiClient(tokenManager);
        const models = await apiClient.getAvailableModels();
        return c.json(models);
    } catch (e: any) {
        return c.json({ error: e.message }, 500);
    }
});

app.post('/v1/chat/completions', async (c) => {
    try {
        const body = await c.req.json();
        const tokenManager = new TokenManager(c.env.ACCOUNTS, c.env.TOKEN_CACHE);
        const apiClient = new ApiClient(tokenManager);

        // Validate required fields (simplified)
        if (!body.messages || !body.model) {
            return c.json({ error: 'Missing messages or model' }, 400);
        }

        // Get a token to ensure we can proceed
        const token = await tokenManager.getToken();
        if (!token) {
            return c.json({ error: 'No available accounts' }, 503);
        }

        const upstreamBody = generateRequestBody(token, body.messages, body.model, body);

        // Default to streaming if not specified
        const stream = body.stream ?? true;

        if (stream) {
            const { readable, writable } = new TransformStream();
            const writer = writable.getWriter();
            const encoder = new TextEncoder();

            c.executionCtx.waitUntil(async function () {
                try {
                    const generator = apiClient.generateAssistantResponse(upstreamBody);
                    const created = Math.floor(Date.now() / 1000);
                    const id = `chatcmpl-${crypto.randomUUID()}`;

                    for await (const chunk of generator) {
                        if (chunk.type === 'text') {
                            const responseChunk = {
                                id,
                                object: 'chat.completion.chunk',
                                created,
                                model: body.model,
                                choices: [{ index: 0, delta: { content: chunk.content }, finish_reason: null }]
                            };
                            await writer.write(encoder.encode(`data: ${JSON.stringify(responseChunk)}\n\n`));
                        } else if (chunk.type === 'thinking') {
                            // Output thinking content as regular content chunks
                            const responseChunk = {
                                id,
                                object: 'chat.completion.chunk',
                                created,
                                model: body.model,
                                choices: [{ index: 0, delta: { content: chunk.content }, finish_reason: null }]
                            };
                            await writer.write(encoder.encode(`data: ${JSON.stringify(responseChunk)}\n\n`));
                        } else if (chunk.type === 'tool_calls') {
                            const responseChunk = {
                                id,
                                object: 'chat.completion.chunk',
                                created,
                                model: body.model,
                                choices: [{ index: 0, delta: { tool_calls: chunk.tool_calls }, finish_reason: null }]
                            };
                            await writer.write(encoder.encode(`data: ${JSON.stringify(responseChunk)}\n\n`));
                        }
                    }

                    const finalChunk = {
                        id,
                        object: 'chat.completion.chunk',
                        created,
                        model: body.model,
                        choices: [{ index: 0, delta: {}, finish_reason: 'stop' }]
                    };
                    await writer.write(encoder.encode(`data: ${JSON.stringify(finalChunk)}\n\n`));
                    await writer.write(encoder.encode('data: [DONE]\n\n'));
                } catch (e: any) {
                    console.error('Streaming error:', e);
                    const errorChunk = { error: e.message };
                    await writer.write(encoder.encode(`data: ${JSON.stringify(errorChunk)}\n\n`));
                } finally {
                    await writer.close();
                }
            }());

            return new Response(readable, {
                headers: {
                    'Content-Type': 'text/event-stream',
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                },
            });

        } else {
            // Non-streaming
            let fullContent = '';
            let toolCalls: any[] = [];
            const generator = apiClient.generateAssistantResponse(upstreamBody);
            for await (const chunk of generator) {
                if (chunk.type === 'text' || chunk.type === 'thinking') {
                    fullContent += chunk.content;
                } else if (chunk.type === 'tool_calls') {
                    toolCalls = chunk.tool_calls || [];
                }
            }

            const message: any = { role: 'assistant', content: fullContent };
            if (toolCalls.length > 0) {
                message.tool_calls = toolCalls;
            }

            return c.json({
                id: `chatcmpl-${crypto.randomUUID()}`,
                object: 'chat.completion',
                created: Math.floor(Date.now() / 1000),
                model: body.model,
                choices: [{
                    index: 0,
                    message: message,
                    finish_reason: toolCalls.length > 0 ? 'tool_calls' : 'stop'
                }]
            });
        }

    } catch (e: any) {
        console.error('Error in chat completion:', e);
        return c.json({ error: e.message }, 500);
    }
});

export default app;
