import requests
import json
import os
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# GHL OAuth token refresh URL
token_url = "https://services.leadconnectorhq.com/oauth/token"

# Client configurations
clients = {
    'Storm Central': {
        'client_id': '682c83da4b23f3a72b146405-mb5f9s4w',
        'client_secret': '4cd4b8b5-fcad-4875-a56f-da24b7add34e',
        'refresh_token': 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdXRoQ2xhc3MiOiJMb2NhdGlvbiIsImF1dGhDbGFzc0lkIjoibFhWOTY2UGNkOXdyRXl5T2RETmEiLCJzb3VyY2UiOiJJTlRFR1JBVElPTiIsInNvdXJjZUlkIjoiNjgyYzgzZGE0YjIzZjNhNzJiMTQ2NDA1LW1iNWY5czR3IiwiY2hhbm5lbCI6Ik9BVVRIIiwicHJpbWFyeUF1dGhDbGFzc0lkIjoibFhWOTY2UGNkOXdyRXl5T2RETmEiLCJvYXV0aE1ldGEiOnsic2NvcGVzIjpbImNvbnRhY3RzLnJlYWRvbmx5IiwiY29udGFjdHMud3JpdGUiLCJmb3Jtcy5yZWFkb25seSIsImNhbGVuZGFycy53cml0ZSIsImNhbGVuZGFycy5yZWFkb25seSIsInVzZXJzLndyaXRlIiwidXNlcnMucmVhZG9ubHkiXSwiY2xpZW50IjoiNjgyYzgzZGE0YjIzZjNhNzJiMTQ2NDA1IiwidmVyc2lvbklkIjoiNjgyYzgzZGE0YjIzZjNhNzJiMTQ2NDA1IiwiY2xpZW50S2V5IjoiNjgyYzgzZGE0YjIzZjNhNzJiMTQ2NDA1LW1iNWY5czR3In0sImlhdCI6MTc1MDk0NTIzNC42NzMsImV4cCI6MTc4MjQ4MTIzNC42NzMsInVuaXF1ZUlkIjoiZjRlZWUyMjMtMjY1ZS00YzcwLTkxN2QtNjQ2MGFkZDkwNjRhIiwidiI6IjIifQ.Uk8mlbpGJakbzDpeSo8GNkdxHR6QoQo0Kqek_VhOkQwpNYFGTu0fn9qtLQ0dzuoVhpQSinZHLljwqMBqIdgA_PnLxz2COfLNbK4OopBQ4_pxh8kn-SxZirH3C1hhWCPK94z2UnMKn_C4_cC4WmNh44y_qzI_9jQBwvg95SNOh-ZAeiD86zMwyWS4tZXPODRubnfCMPw9saMRCws9lAxbKG4fcUJFGUju1sKPIzOq2AriiIh9Or-kzKapfnzNZw1u_jv_31MphwUj2-gNSpWlCf31sMbXxCRHKQ4BDWFroeaci2NYqpQJh3aZZEJID8IhGVK0XNw_A15wgZr8PjUg6sY7ndOy_6kaJ7SvvPKFG3i1wRSZrYnKMW1EorzHMv6xkjCKLf7myTrPdifJJfbs7uAGFMLDxCwBAPWWrdaIIGBXoVcbrYOPlkb2cB6ffgmzG_TZUOsRmku9hN53KRDKhor9dKXXzFJoRYWkFQ5Nso9a5XLYTATb-yWiT8FTnWrRZSzpbCa8EQDfFWwVyyRVYlEOizddIh6Y7ZLcLfItUmQPqgPoBvE-cBz_Yesfpx_5T2LDQwEIWe727bHFw-mnRXtGo4bibrnBc5IoOurrSILSfwKPGAEe4TUoEj4KZjuSvPCmZS61aGHJemB2_ksHj5TEy813uDKf0pN25Iqwl2c',  # hardcoded refresh token for first run
        'token_file': 'tokens.json'
    }
}

def make_request(token_url, data, client_name):
    """Make a request to the token endpoint"""
    try:
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"[{client_name}] Request Error: {str(e)}")
        return None

def refresh_token(token_url, client_name, client_data):
    """Refresh the OAuth token for a client"""
    # Check if the token file exists, if not use the hardcoded refresh token for the first run
    location_id = None
    company_id = None
    
    if os.path.exists(client_data['token_file']):
        try:
            with open(client_data['token_file'], 'r') as file:
                data = json.load(file)
            latest_refresh_token = data['refresh_token']
            
            # Preserve existing location_id and company_id if available
            location_id = data.get('location_id')
            company_id = data.get('company_id')
            
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"[{client_name}] Error reading token file: {str(e)}")
            return
    else:
        # First run, use the hardcoded refresh token
        latest_refresh_token = client_data['refresh_token']

    # Prepare the data for the request
    data = {
        'grant_type': 'refresh_token',
        'client_id': client_data['client_id'],
        'client_secret': client_data['client_secret'],
        'refresh_token': latest_refresh_token,
        'user_type': 'Location'
    }

    # Make the request to get the new access token
    response_data = make_request(token_url, data, client_name)

    if response_data and 'access_token' in response_data:
        access_token = response_data['access_token']
        refresh_token = response_data['refresh_token']
        
        # Extract location_id and company_id from token if possible
        try:
            # Parse JWT token to extract location ID if not already available
            import jwt
            decoded_token = jwt.decode(access_token, options={"verify_signature": False})
            
            # Extract location ID from token if available
            if not location_id and 'authClassId' in decoded_token:
                location_id = decoded_token['authClassId']
                logging.info(f"[{client_name}] Extracted location_id from token: {location_id}")
            
            # Extract company ID if available in token
            if not company_id and 'companyId' in decoded_token:
                company_id = decoded_token['companyId']
                logging.info(f"[{client_name}] Extracted company_id from token: {company_id}")
                
        except Exception as e:
            logging.warning(f"[{client_name}] Could not extract additional data from token: {e}")
            
        # Calculate token expiration time (default to 24 hours if not in token)
        token_expires_at = datetime.now() + timedelta(hours=24)
        try:
            # Try to get expiration from token
            if 'exp' in decoded_token:
                token_expires_at = datetime.fromtimestamp(decoded_token['exp'])
        except:
            pass

        # Prepare the new token data with all parameters
        token_data = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'token_expires_at': token_expires_at.isoformat(),
        }
        
        # Add location_id and company_id if available
        if location_id:
            token_data['location_id'] = location_id
        
        if company_id:
            token_data['company_id'] = company_id

        # Save the new tokens to the file
        try:
            with open(client_data['token_file'], 'w') as file:
                json.dump(token_data, file, indent=4)
            logging.info(f"[{client_name}] Access token saved to {client_data['token_file']} successfully.")
            logging.info(f"[{client_name}] Token will expire at: {token_expires_at}")
        except IOError as e:
            logging.error(f"[{client_name}] Error writing the access token to {client_data['token_file']}: {str(e)}")
    else:
        # Handle error if the token request fails
        error_message = response_data.get('error', 'Unknown error') if response_data else 'Request failed'
        logging.error(f"[{client_name}] Error fetching access token: {error_message}")

def refresh_all_tokens():
    """Refresh tokens for all configured clients - can be imported and called from other scripts"""
    for client_name, client_data in clients.items():
        refresh_token(token_url, client_name, client_data)
    
    logging.info("Token refresh process completed for all clients.")
    return True

def main():
    """Main function to refresh tokens for all clients"""
    refresh_all_tokens()

if __name__ == "__main__":
    main() 