import os
import json
import time
import logging
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants for Google OAuth
CLIENT_ID = '1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com'
CLIENT_SECRET = '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'
TOKEN_URI = 'https://oauth2.googleapis.com/token'

# Default path to the accounts file
ACCOUNTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'accounts.json')

class TokenManager:
    """Manages reading, refreshing, and providing OAuth tokens from a file."""

    def __init__(self, accounts_file=ACCOUNTS_FILE):
        """
        Initializes the TokenManager.
        Args:
            accounts_file (str): Path to the JSON file storing account tokens.
        """
        self.accounts_file = accounts_file
        # Use a simple round-robin index to rotate tokens
        self.current_token_index = 0

    def _read_accounts(self):
        """Reads and parses the accounts from the JSON file."""
        if not os.path.exists(self.accounts_file):
            return []
        try:
            with open(self.accounts_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Error reading accounts file {self.accounts_file}: {e}")
            return []

    def _write_accounts(self, accounts):
        """Writes the updated accounts list back to the JSON file."""
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(self.accounts_file), exist_ok=True)
            with open(self.accounts_file, 'w', encoding='utf-8') as f:
                json.dump(accounts, f, indent=2)
        except IOError as e:
            logging.error(f"Error writing to accounts file {self.accounts_file}: {e}")

    def _refresh_token(self, account):
        """Refreshes an access token using its refresh token."""
        logging.info("Access token expired, attempting to refresh...")
        refresh_token = account.get('refresh_token')
        if not refresh_token:
            logging.warning("Account has no refresh token. Cannot refresh.")
            return None
        
        payload = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
        }
        
        try:
            response = requests.post(TOKEN_URI, data=payload, timeout=10)
            response.raise_for_status()  # Raises HTTPError for bad responses
            
            new_token_data = response.json()
            account['access_token'] = new_token_data['access_token']
            account['expires_in'] = new_token_data['expires_in']
            account['timestamp'] = int(time.time())
            
            logging.info("Successfully refreshed access token.")
            return account
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to refresh token: {e}")
            if e.response is not None:
                logging.error(f"Refresh error response: {e.response.text}")
            return None

    def get_token(self):
        """
        Gets a valid token from the accounts file. It tries tokens in a round-robin
        fashion and automatically refreshes them if they are expired.
        """
        accounts = self._read_accounts()
        if not accounts:
            return None

        num_accounts = len(accounts)
        # Iterate through all available accounts to find a valid one
        for i in range(num_accounts):
            # Use round-robin to avoid hammering the same token
            index = (self.current_token_index + i) % num_accounts
            account = accounts[index]

            if account.get("disabled"):
                continue

            # Check if token is expired, with a 60-second buffer
            is_expired = (account.get('timestamp', 0) + account.get('expires_in', 0) - 60) < time.time()

            if is_expired:
                refreshed_account = self._refresh_token(account)
                if refreshed_account:
                    # Update account list and write back to file
                    accounts[index] = refreshed_account
                    self._write_accounts(accounts)
                    # Advance the index for next call
                    self.current_token_index = (index + 1) % num_accounts
                    return refreshed_account
                else:
                    # If refresh fails, do not disable the token to allow for retries
                    logging.warning(f"Refresh failed for token with refresh_token starting with '{str(account.get('refresh_token'))[:10]}'. Will try next token.")
                    continue  # Try the next account
            else:
                # Token is valid, return it
                self.current_token_index = (index + 1) % num_accounts
                return account
        
        logging.error("No valid and refreshable tokens found in the accounts file.")
        return None

