export interface ChatMessage {
    role: string;
    content: any; // string or multimodal list
    tool_calls?: any[];
    tool_call_id?: string;
    [key: string]: any;
}

export interface ChatCompletionRequest {
    messages: ChatMessage[];
    model: string;
    stream?: boolean;
    tools?: any[];
    temperature?: number;
    top_p?: number;
    max_tokens?: number;
    [key: string]: any;
}

export interface Account {
    refresh_token: string;
    access_token?: string;
    expires_in?: number;
    timestamp?: number;
    disabled?: boolean;
    projectId?: string;
    sessionId?: string;
}

export interface TokenCache {
    access_token: string;
    expires_in: number;
    timestamp: number;
}

export interface Env {
    ACCOUNTS: string; // JSON string stored as secret (refresh tokens)
    TOKEN_CACHE: KVNamespace; // KV store for access tokens
    API_KEY: string;
}
