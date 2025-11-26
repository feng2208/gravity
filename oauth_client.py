
import http.server
import socketserver
import webbrowser
import requests
import json
import os
import secrets
import logging
from urllib.parse import urlparse, parse_qs, urlencode
from threading import Thread
import time

# ==============================================================================
# Configuration
# ==============================================================================
# This script requires the 'requests' library.
# You can install it by running: pip install requests
# ==============================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants based on the Node.js script ---
CLIENT_ID = '1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com'
CLIENT_SECRET = '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'
SCOPES = [
  'https://www.googleapis.com/auth/cloud-platform',
  'https://www.googleapis.com/auth/userinfo.email',
  'https://www.googleapis.com/auth/userinfo.profile',
  'https://www.googleapis.com/auth/cclog',
  'https://www.googleapis.com/auth/experimentsandconfigs'
]

# --- File path for storing credentials ---
# Note: This will create a 'data' directory in the same directory as the script.
ACCOUNTS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'accounts.json')

# --- Global state for the server ---
# This dictionary holds server details to be accessible by the request handler.
SERVER_STATE = {
    "server": None,
    "state_token": secrets.token_urlsafe(16),
    "port": 0
}


def generate_auth_url():
    """Generates the Google OAuth2 authorization URL."""
    params = {
        'access_type': 'offline',
        'client_id': CLIENT_ID,
        'prompt': 'consent',
        'redirect_uri': f'http://localhost:{SERVER_STATE["port"]}/oauth-callback',
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'state': SERVER_STATE["state_token"]
    }
    encoded_params = urlencode(params)
    return f"https://accounts.google.com/o/oauth2/v2/auth?{encoded_params}"


def exchange_code_for_token(code):
    """Exchanges the authorization code for an access token and refresh token."""
    logging.info("Exchanging authorization code for token...")
    try:
        post_data = {
            'code': code,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': f'http://localhost:{SERVER_STATE["port"]}/oauth-callback',
            'grant_type': 'authorization_code'
        }
        
        response = requests.post('https://oauth2.googleapis.com/token', data=post_data, timeout=10)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx) 
        
        token_data = response.json()
        logging.info("Successfully exchanged code for token.")
        return token_data

    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to exchange token: {e}")
        if e.response:
            logging.error(f"Response body: {e.response.text}")
        return None


def save_token(token_data):
    """Saves the token data to the accounts JSON file."""
    account = {
        'access_token': token_data.get('access_token'),
        'refresh_token': token_data.get('refresh_token'),
        'expires_in': token_data.get('expires_in'),
        'timestamp': int(time.time())
    }

    accounts = []
    try:
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        logging.warning(f"Could not read {ACCOUNTS_FILE}, a new file will be created. Error: {e}")

    accounts.append(account)

    try:
        # Ensure the 'data' directory exists before writing the file.
        os.makedirs(os.path.dirname(ACCOUNTS_FILE), exist_ok=True)
        
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=2)
        logging.info(f"Token data saved successfully to {ACCOUNTS_FILE}")
    except IOError as e:
        logging.error(f"Failed to write to {ACCOUNTS_FILE}. Error: {e}")


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """A simple HTTP request handler for the OAuth2 callback."""

    def do_GET(self):
        """Handles GET requests sent to the server."""
        url_parts = urlparse(self.path)
        query_params = parse_qs(url_parts.query)
        
        # --- Shutdown Helper ---
        # This function will be called in a separate thread to prevent blocking.
        def stop_server():
            time.sleep(1) # Give the browser a moment to render the response
            if SERVER_STATE["server"]:
                SERVER_STATE["server"].shutdown()

        shutdown_thread = Thread(target=stop_server)

        if url_parts.path == '/oauth-callback':
            html_content = ""
            code = query_params.get('code', [None])[0]
            state = query_params.get('state', [None])[0]
            error = query_params.get('error', [None])[0]
            
            # Security check: Ensure the 'state' token matches.
            if state != SERVER_STATE["state_token"]:
                logging.error("State token mismatch. Possible CSRF attack detected.")
                html_content = "<h1>Authorization Failed</h1><p>Invalid state token.</p>"
            elif error:
                logging.error(f"Authorization failed with error: {error}")
                html_content = f"<h1>Authorization Failed</h1><p>Error: {error}</p>"
            elif code:
                logging.info("Authorization code received.")
                token_data = exchange_code_for_token(code)
                if token_data:
                    save_token(token_data)
                    html_content = "<h1>Authorization Successful!</h1><p>Token has been saved. You can now close this page.</p>"
                else:
                    html_content = "<h1>Token Exchange Failed</h1><p>Please check the console for error details.</p>"
            else:
                 html_content = "<h1>Authorization Failed</h1><p>No authorization code was received from Google.</p>"
            
            # Send a response back to the browser.
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html_content.encode('utf-8'))
            
            # Initiate the server shutdown.
            shutdown_thread.start()
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Not Found')

    def log_message(self, format, *args):
        # Suppress the default request logging to keep the console clean.
        return


def main():
    """Main function to orchestrate the OAuth flow."""
    # Using port 0 lets the OS automatically select an available ephemeral port.
    with http.server.HTTPServer(('localhost', 0), OAuthCallbackHandler) as server:
        SERVER_STATE["server"] = server
        SERVER_STATE["port"] = server.server_port
        
        auth_url = generate_auth_url()
        
        logging.info(f"Server running on http://localhost:{server.server_port}")
        logging.info("Please open the following URL in your browser to log in:")
        print(f"\n{auth_url}\n")
        
        # Attempt to automatically open the URL in the user's default browser.
        try:
            webbrowser.open(auth_url)
            logging.info("Attempted to open the URL in your browser automatically.")
        except Exception as e:
            logging.warning(f"Could not automatically open browser: {e}")
        
        logging.info("Waiting for authorization callback from Google...")
        
        # This call blocks until server.shutdown() is invoked by the request handler.
        server.serve_forever()
        logging.info("Server has been shut down.")


if __name__ == '__main__':
    main()
