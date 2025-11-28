# Cloudflare Workers Deployment Guide

## Prerequisites
- Cloudflare account
- Wrangler CLI installed (`npm install -g wrangler`)
- Logged in to Cloudflare (`npx wrangler login`)

## Architecture Overview

This worker uses a hybrid storage approach:
- **ACCOUNTS secret**: Stores refresh tokens (read-only, secure)
- **TOKEN_CACHE KV**: Stores access tokens (read-write, automatically refreshed)

This provides the best of both worlds: secure refresh token storage and persistent access token caching.

## Step-by-Step Deployment

### 1. Create KV Namespace for Token Cache
```powershell
npx wrangler kv namespace create TOKEN_CACHE
```

**Output example:**
```
🌀 Creating namespace with title "openai-compatible-proxy-TOKEN_CACHE"
✨ Success!
Add the following to your configuration file in your kv_namespaces array:
{ binding = "TOKEN_CACHE", id = "abc123def456" }
```

Copy the `id` value and update `wrangler.toml`:
```toml
[[kv_namespaces]]
binding = "TOKEN_CACHE"
id = "abc123def456"  # Replace with your actual ID
```

### 2. Set API_KEY Secret
```powershell
npx wrangler secret put API_KEY
```
When prompted, enter your API key value (e.g., `your-secret-api-key-here`).

### 3. Set ACCOUNTS Secret
```powershell
npx wrangler secret put ACCOUNTS
```
When prompted, enter the JSON array of accounts with **only refresh tokens**:
```json
[{"refresh_token":"YOUR_REFRESH_TOKEN_HERE"}]
```

**Important notes:**
- Only `refresh_token` is required in the ACCOUNTS secret
- Access tokens will be automatically cached in the TOKEN_CACHE KV
- You can include optional fields like `disabled`, `projectId`, `sessionId`

**Example with multiple accounts:**
```json
[
  {"refresh_token":"TOKEN_1"},
  {"refresh_token":"TOKEN_2","disabled":false}
]
```

### 4. Deploy the Worker
```powershell
npx wrangler deploy
```

**Output example:**
```
Total Upload: xx.xx KiB / gzip: xx.xx KiB
Uploaded openai-compatible-proxy (x.xx sec)
Published openai-compatible-proxy (x.xx sec)
  https://openai-compatible-proxy.your-subdomain.workers.dev
```

### 5. Test the Deployment
```powershell
# Test the models endpoint
curl https://openai-compatible-proxy.your-subdomain.workers.dev/v1/models

# Test chat completion
curl https://openai-compatible-proxy.your-subdomain.workers.dev/v1/chat/completions \
  -H "Authorization: Bearer your-secret-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-pro",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## How It Works

1. **First Request**: Worker reads refresh_token from ACCOUNTS secret and uses it to get an access_token from Google OAuth
2. **Caching**: The access_token is saved to TOKEN_CACHE KV with expiration info
3. **Subsequent Requests**: Worker uses cached access_token from KV (fast, no OAuth call needed)
4. **Token Expiry**: When cached token expires, worker automatically refreshes it and updates KV
5. **Persistence**: Refreshed tokens persist across requests because they're in KV

## Managing Secrets

### Update ACCOUNTS secret
```powershell
npx wrangler secret put ACCOUNTS
```

### Delete a secret
```powershell
npx wrangler secret delete ACCOUNTS
```

### List all secrets
```powershell
npx wrangler secret list
```

## Managing KV Token Cache

### View cached tokens
```powershell
npx wrangler kv key list --binding TOKEN_CACHE
```

### View a specific cached token
```powershell
npx wrangler kv key get token_0 --binding TOKEN_CACHE
```

### Clear token cache (force refresh on next request)
```powershell
npx wrangler kv key delete token_0 --binding TOKEN_CACHE
```

## Local Development and Debugging

### Setup

1. **Install dependencies**:
```powershell
npm install
```

2. **Create `.dev.vars` file** in the `worker` directory:
```env
API_KEY=your-secret-api-key
ACCOUNTS=[{"refresh_token":"your_refresh_token_here"}]
```

**Important:** 
- `.dev.vars` is automatically gitignored
- Never commit this file to version control
- Use actual refresh token from your Google OAuth flow

3. **Start local development server**:
```powershell
npx wrangler dev
```

The worker will be available at `http://localhost:8787`.

**Note:** Wrangler will automatically create a local KV storage for TOKEN_CACHE in `.wrangler/state/v3/kv/`.

### Testing Endpoints Locally

#### Health Check
```powershell
curl http://localhost:8787/
# Expected: "OpenAI Compatible Proxy Worker is running!"
```

#### Get Models
```powershell
curl http://localhost:8787/v1/models
```

#### Chat Completion (Streaming - Default)
```powershell
curl http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-pro",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

#### Chat Completion (Non-Streaming)
```powershell
curl http://localhost:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-pro",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

### Debugging Tips

#### View Console Logs
Wrangler dev shows all `console.log()` output in the terminal. Watch for:
- Token refresh messages
- Error messages
- API request/response logs

#### Common Issues

**"No available token" error:**
- Check `.dev.vars` file exists and has valid JSON
- Verify ACCOUNTS format: `[{"refresh_token":"..."}]`
- Restart `wrangler dev` after changing `.dev.vars`

**"Failed to refresh token" error:**
- Verify your refresh_token is valid
- Check if the OAuth client credentials are correct in `token_manager.ts`
- Ensure your Google account has the necessary permissions

**CORS errors in browser:**
- The worker has CORS enabled by default
- If testing from a web app, ensure your API_KEY is passed correctly

### Remote Debugging (Testing Against Local Worker from Other Devices)

By default, wrangler dev binds to `0.0.0.0:8787` (configured in `wrangler.toml`), making it accessible on your local network.

To access from another device:
1. Find your computer's local IP (e.g., `192.168.1.100`)
2. Access the worker at `http://192.168.1.100:8787`

This is useful for testing from mobile devices or other machines.

## Troubleshooting

### "No available token" error
- Check that ACCOUNTS secret is set: `npx wrangler secret list`
- Verify the JSON format is valid
- Check that at least one account is not disabled

### Tokens not persisting
- Verify TOKEN_CACHE KV namespace is created and bound correctly in `wrangler.toml`
- Check KV namespace ID matches the one from `npx wrangler kv namespace create`

### Frequent token refreshes
- Check the cached tokens: `npx wrangler kv key list --binding TOKEN_CACHE`
- Ensure tokens are being saved to KV (check worker logs)
