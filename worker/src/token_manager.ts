import { Account, TokenCache } from './types';

const CLIENT_ID = '1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com';
const CLIENT_SECRET = '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';
const TOKEN_URI = 'https://oauth2.googleapis.com/token';

export class TokenManager {
    private accountsSecret: string;
    private tokenCache: KVNamespace;

    constructor(accountsSecret: string, tokenCache: KVNamespace) {
        this.accountsSecret = accountsSecret;
        this.tokenCache = tokenCache;
    }

    getAccounts(): Account[] {
        if (!this.accountsSecret) return [];
        try {
            return JSON.parse(this.accountsSecret);
        } catch (e) {
            console.error('Error parsing accounts from secret:', e);
            return [];
        }
    }

    async getTokenFromCache(accountIndex: number): Promise<TokenCache | null> {
        const cacheKey = `token_${accountIndex}`;
        const cached = await this.tokenCache.get(cacheKey);
        if (!cached) return null;

        try {
            return JSON.parse(cached) as TokenCache;
        } catch (e) {
            console.error('Error parsing cached token:', e);
            return null;
        }
    }

    async saveTokenToCache(accountIndex: number, tokenCache: TokenCache): Promise<void> {
        const cacheKey = `token_${accountIndex}`;
        await this.tokenCache.put(cacheKey, JSON.stringify(tokenCache));
    }

    async refreshToken(account: Account): Promise<TokenCache | null> {
        console.log('Refreshing token...');
        if (!account.refresh_token) return null;

        try {
            const response = await fetch(TOKEN_URI, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({
                    client_id: CLIENT_ID,
                    client_secret: CLIENT_SECRET,
                    refresh_token: account.refresh_token,
                    grant_type: 'refresh_token',
                }),
            });

            if (!response.ok) {
                console.error('Failed to refresh token:', await response.text());
                return null;
            }

            const data: any = await response.json();
            return {
                access_token: data.access_token,
                expires_in: data.expires_in,
                timestamp: Math.floor(Date.now() / 1000)
            };
        } catch (e) {
            console.error('Error refreshing token:', e);
            return null;
        }
    }

    async getToken(): Promise<Account | null> {
        const accounts = this.getAccounts();
        if (accounts.length === 0) return null;

        // Try each account in round-robin fashion
        for (let i = 0; i < accounts.length; i++) {
            const account = accounts[i];
            if (account.disabled) continue;

            // Try to get from cache first
            const cached = await this.getTokenFromCache(i);

            const now = Math.floor(Date.now() / 1000);
            const isExpired = cached
                ? (cached.timestamp + cached.expires_in - 60 < now)
                : true;

            if (isExpired || !cached) {
                // Refresh the token
                const refreshed = await this.refreshToken(account);
                if (refreshed) {
                    // Save to cache
                    await this.saveTokenToCache(i, refreshed);

                    // Return account with fresh token
                    return {
                        ...account,
                        access_token: refreshed.access_token,
                        expires_in: refreshed.expires_in,
                        timestamp: refreshed.timestamp
                    };
                } else {
                    console.warn('Failed to refresh token, trying next account');
                    continue;
                }
            } else {
                // Use cached token
                return {
                    ...account,
                    access_token: cached.access_token,
                    expires_in: cached.expires_in,
                    timestamp: cached.timestamp
                };
            }
        }

        return null;
    }
}
