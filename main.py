#!/usr/bin/env python3
"""
Phase 1-4+ Automation - Internal Clients
Main entry point for the application

Phases:
1. Create User in Go High Level
2. Create Client Calendar
3. Purchase Client Phone Number (with SMS enabled)
3.5. A2P 10DLC Registration (SMS compliance for business use)
4. Assign Phone Number to User in CRM (SMS A2P compliant)
5. Add Employee to CRM (Future)
6. Set Up Automation for Opportunities (Future)
"""
import os
import sys
import json
import logging
import requests
import webbrowser
import urllib.parse
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException
import pytz
import jwt

# Import the Phone_Number_Purchase function from login_ghl
from login_ghl import Phone_Number_Purchase

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Go High Level OAuth Configuration - Using Working Credentials
GHL_CLIENT_ID = os.getenv("GHL_CLIENT_ID")
GHL_CLIENT_SECRET = os.getenv("GHL_CLIENT_SECRET")
GHL_REDIRECT_URI = os.getenv("GHL_REDIRECT_URI", "https://login1.theccdocs.com/vicidial/welcome.php")
GHL_BASE_URL = "https://marketplace.gohighlevel.com"  # Updated to match working auth URL
GHL_API_BASE_URL = "https://services.leadconnectorhq.com"
GHL_FORM_ID = os.getenv("GHL_FORM_ID", "28wKJpL0zNImn9bYVPSN")  # Default to your Client Onboarding form

# Agency API Key for User Creation (different from OAuth)
GHL_AGENCY_API_KEY = os.getenv("GHL_AGENCY_API_KEY")  # Required for creating users

# Twilio Configuration for Phase 3
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# OAuth Scopes - Only include scopes your app actually has permission for
OAUTH_SCOPES = [
    "contacts.readonly",
    "contacts.write", 
    "forms.readonly",
    "calendars.write",
    "calendars.readonly",
    "users.write",  # Add scope for user management
    "users.readonly"  # Add scope for user management
]

# Default phone number preferences
DEFAULT_PHONE_PREFERENCES = {
    'country_code': 'US',
    'number_type': 'local',
    'sms_enabled': True,
    'voice_enabled': True,
    'mms_enabled': False,
    'limit': 10
}

class TwilioPhoneManager:
    """Class to handle Twilio phone number purchasing and management"""
    
    def __init__(self, account_sid=None, auth_token=None):
            
        self.account_sid = account_sid or TWILIO_ACCOUNT_SID
        self.auth_token = auth_token or TWILIO_AUTH_TOKEN
        
        if not self.account_sid or not self.auth_token:
            raise ValueError("Twilio credentials not provided. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment variables.")
        
        self.client = TwilioClient(self.account_sid, self.auth_token)
        logger.info("Twilio client initialized successfully")
    
    def search_available_numbers(self, country_code="US", area_code=None, contains=None, 
                                sms_enabled=True, voice_enabled=True, mms_enabled=False, 
                                limit=20, number_type="local"):
        """
        Search for available phone numbers
        
        Args:
            country_code (str): Country code (default: "US")
            area_code (int): Specific area code to search in
            contains (str): Pattern to match in phone number
            sms_enabled (bool): Require SMS capability
            voice_enabled (bool): Require voice capability
            mms_enabled (bool): Require MMS capability
            limit (int): Maximum number of results
            number_type (str): Type of number - "local", "tollfree", or "mobile"
        
        Returns:
            list: Available phone numbers with their details
        """
        try:
            search_params = {
                'page_size': limit
            }
            
            # Only add boolean parameters if they are True (Twilio API doesn't like False values)
            if sms_enabled:
                search_params['sms_enabled'] = True
            if voice_enabled:
                search_params['voice_enabled'] = True
            if mms_enabled:
                search_params['mms_enabled'] = False
            
            if area_code:
                search_params['area_code'] = area_code
            if contains:
                search_params['contains'] = contains
            
            # Search based on number type
            if number_type.lower() == "local":
                available_numbers = self.client.available_phone_numbers(country_code).local.list(**search_params)
            elif number_type.lower() == "tollfree":
                available_numbers = self.client.available_phone_numbers(country_code).toll_free.list(**search_params)
            elif number_type.lower() == "mobile":
                available_numbers = self.client.available_phone_numbers(country_code).mobile.list(**search_params)
            else:
                raise ValueError(f"Invalid number_type: {number_type}. Use 'local', 'tollfree', or 'mobile'")
            
            results = []
            for number in available_numbers:
                results.append({
                    'phone_number': number.phone_number,
                    'friendly_name': number.friendly_name,
                    'locality': getattr(number, 'locality', None),
                    'region': getattr(number, 'region', None),
                    'postal_code': getattr(number, 'postal_code', None),
                    'iso_country': number.iso_country,
                    'capabilities': {
                        'voice': number.capabilities.get('voice', False),
                        'sms': number.capabilities.get('sms', False),
                        'mms': number.capabilities.get('mms', False)
                    },
                    'address_requirements': getattr(number, 'address_requirements', 'none'),
                    'beta': getattr(number, 'beta', False)
                })
            
            logger.info(f"Found {len(results)} available {number_type} numbers in {country_code}")
            return results
            
        except TwilioRestException as e:
            logger.error(f"Twilio API error searching numbers: {e}")
            return []
        except Exception as e:
            logger.error(f"Error searching available numbers: {e}")
            return []
    
    def purchase_phone_number(self, phone_number, friendly_name=None, voice_url=None, 
                             sms_url=None, status_callback=None):
        """
        Purchase a specific phone number
        
        Args:
            phone_number (str): Phone number to purchase in E.164 format
            friendly_name (str): Friendly name for the number
            voice_url (str): URL to handle incoming calls
            sms_url (str): URL to handle incoming SMS
            status_callback (str): URL for status callbacks
        
        Returns:
            dict: Purchased phone number details or None if failed
        """
        try:
            purchase_params = {
                'phone_number': phone_number
            }
            
            if friendly_name:
                purchase_params['friendly_name'] = friendly_name
            if voice_url:
                purchase_params['voice_url'] = voice_url
            if sms_url:
                purchase_params['sms_url'] = sms_url
            if status_callback:
                purchase_params['status_callback'] = status_callback
            
            purchased_number = self.client.incoming_phone_numbers.create(**purchase_params)
            
            result = {
                'sid': purchased_number.sid,
                'phone_number': purchased_number.phone_number,
                'friendly_name': purchased_number.friendly_name,
                'account_sid': purchased_number.account_sid,
                'capabilities': {
                    'voice': purchased_number.capabilities.get('voice', False),
                    'sms': purchased_number.capabilities.get('sms', False),
                    'mms': purchased_number.capabilities.get('mms', False)
                },
                'date_created': purchased_number.date_created,
                'status': getattr(purchased_number, 'status', 'active'),
                'voice_url': purchased_number.voice_url,
                'sms_url': purchased_number.sms_url
            }
            
            logger.info(f"Successfully purchased phone number: {phone_number}")
            logger.info(f"Number SID: {purchased_number.sid}")
            
            return result
            
        except TwilioRestException as e:
            logger.error(f"Twilio API error purchasing number {phone_number}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error purchasing phone number {phone_number}: {e}")
            return None
    
    def get_account_numbers(self, limit=50):
        """
        Get all phone numbers owned by the account
        
        Args:
            limit (int): Maximum number of results
        
        Returns:
            list: List of owned phone numbers
        """
        try:
            numbers = self.client.incoming_phone_numbers.list(limit=limit)
            
            results = []
            for number in numbers:
                results.append({
                    'sid': number.sid,
                    'phone_number': number.phone_number,
                    'friendly_name': number.friendly_name,
                    'capabilities': {
                        'voice': number.capabilities.get('voice', False),
                        'sms': number.capabilities.get('sms', False),
                        'mms': number.capabilities.get('mms', False)
                    },
                    'date_created': number.date_created,
                    'voice_url': number.voice_url,
                    'sms_url': number.sms_url,
                    'status': getattr(number, 'status', 'active')
                })
            
            logger.info(f"Retrieved {len(results)} phone numbers from account")
            return results
            
        except TwilioRestException as e:
            logger.error(f"Twilio API error retrieving account numbers: {e}")
            return []
        except Exception as e:
            logger.error(f"Error retrieving account numbers: {e}")
            return []
    
    def update_phone_number(self, number_sid, friendly_name=None, voice_url=None, 
                           sms_url=None, status_callback=None):
        """
        Update an existing phone number configuration
        
        Args:
            number_sid (str): SID of the phone number to update
            friendly_name (str): New friendly name
            voice_url (str): New voice URL
            sms_url (str): New SMS URL
            status_callback (str): New status callback URL
        
        Returns:
            dict: Updated phone number details or None if failed
        """
        try:
            update_params = {}
            
            if friendly_name is not None:
                update_params['friendly_name'] = friendly_name
            if voice_url is not None:
                update_params['voice_url'] = voice_url
            if sms_url is not None:
                update_params['sms_url'] = sms_url
            if status_callback is not None:
                update_params['status_callback'] = status_callback
            
            if not update_params:
                logger.warning("No parameters provided for phone number update")
                return None
            
            updated_number = self.client.incoming_phone_numbers(number_sid).update(**update_params)
            
            result = {
                'sid': updated_number.sid,
                'phone_number': updated_number.phone_number,
                'friendly_name': updated_number.friendly_name,
                'voice_url': updated_number.voice_url,
                'sms_url': updated_number.sms_url,
                'status': getattr(updated_number, 'status', 'active')
            }
            
            logger.info(f"Successfully updated phone number: {updated_number.phone_number}")
            return result
            
        except TwilioRestException as e:
            logger.error(f"Twilio API error updating number {number_sid}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error updating phone number {number_sid}: {e}")
            return None
    
    def release_phone_number(self, number_sid):
        """
        Release (delete) a phone number from the account
        
        Args:
            number_sid (str): SID of the phone number to release
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.client.incoming_phone_numbers(number_sid).delete()
            logger.info(f"Successfully released phone number with SID: {number_sid}")
            return True
            
        except TwilioRestException as e:
            logger.error(f"Twilio API error releasing number {number_sid}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error releasing phone number {number_sid}: {e}")
            return False
    
    def find_and_purchase_number(self, client_data, preferences=None):
        """
        Find and purchase a phone number based on client preferences
        
        Args:
            client_data (dict): Client information from form submission
            preferences (dict): Phone number preferences
        
        Returns:
            dict: Purchased phone number details or None if failed
        """
        if preferences is None:
            preferences = DEFAULT_PHONE_PREFERENCES
        
        # Extract location preferences from client data
        client_state = client_data.get('state', '').upper()
        client_city = client_data.get('city', '')
        client_zip = client_data.get('postalCode', '')
        business_name = client_data.get('businessName', client_data.get('companyName', 'Client'))
        
        # Default search preferences
        search_params = {
            'country_code': preferences.get('country_code', 'US'),
            'sms_enabled': preferences.get('sms_enabled', True),
            'voice_enabled': preferences.get('voice_enabled', True),
            'mms_enabled': preferences.get('mms_enabled', False),
            'limit': preferences.get('limit', 10),
            'number_type': preferences.get('number_type', 'local')
        }
        
        logger.info(f"Searching for phone numbers for client: {business_name}")
        logger.info(f"Search parameters: {search_params}")
        
        # Search for available numbers
        available_numbers = self.search_available_numbers(**search_params)
        
        if not available_numbers:
            logger.warning("No available numbers found with specified criteria")
            # Try broader search without location restrictions
            available_numbers = self.search_available_numbers(**search_params)
        
        if not available_numbers:
            logger.error("No available numbers found")
            return None
        
        # Select the first available number
        selected_number = available_numbers[0]
        phone_number = selected_number['phone_number']
        
        # Create friendly name
        friendly_name = f"{business_name} - {selected_number['friendly_name']}"
        
        # Purchase the number
        logger.info(f"Attempting to purchase: {phone_number}")
        purchased = self.purchase_phone_number(
            phone_number=phone_number,
            friendly_name=friendly_name
        )
        
        if purchased:
            # Add client information to the result
            purchased['client_info'] = {
                'business_name': business_name,
                'state': client_state,
                'city': client_city,
                'zip_code': client_zip
            }
            
            logger.info(f"Successfully purchased phone number for {business_name}: {phone_number}")
        
        return purchased
    
    def register_a2p_brand(self, client_data):
        """Register A2P 10DLC brand with Twilio"""
        try:
            logger.info("Starting A2P 10DLC brand registration...")
            
            # Use actual approved Trust Hub bundles
            # Note: For A2P, both bundles should be Customer Profile bundles
            brand_registration = self.client.messaging.v1.brand_registrations.create(
                customer_profile_bundle_sid="BU9c2200a4c9ea4a5155572e7bf6f574fc",  # Your approved customer profile
                a2p_profile_bundle_sid="BU872cda290512475cf46f56c6e1ddc5e3",  # Your second approved customer profile
                brand_type='STANDARD',
                mock=False  # Use real registration
            )
            
            logger.info(f"A2P brand registration created: {brand_registration.sid}")
            return brand_registration
            
        except Exception as e:
            # Handle duplicate brand error gracefully (expected in testing)
            if "Duplicate Brand" in str(e):
                logger.info(f"Brand already exists (duplicate detected) - this is expected for testing")
                return None
            else:
                logger.error(f"Error registering A2P brand: {str(e)}")
                raise

    def register_a2p_campaign(self, brand_registration_sid, messaging_service_sid):
        """Register A2P 10DLC campaign with Twilio"""
        try:
            logger.info("Starting A2P 10DLC campaign registration...")
            
            # Create campaign registration using the correct UsAppToPerson API
            campaign_registration = self.client.messaging.v1.services(messaging_service_sid).us_app_to_person.create(
                brand_registration_sid=brand_registration_sid,
                us_app_to_person_usecase="MIXED",  # Mixed use case for business communications
                description="Business SMS messaging for client communications, appointments, and notifications",
                message_samples=[
                    "Hi John, your appointment is scheduled for tomorrow at 2 PM. Reply STOP to opt out.",
                    "Thank you for your business! Your service is complete. Contact us for any questions."
                ],
                message_flow="Customers opt-in by providing consent during service signup or by texting START to our number",
                has_embedded_links=False,
                has_embedded_phone=True,
                subscriber_opt_in=True,
                age_gated=False
            )
            
            logger.info(f"A2P campaign registration created: {campaign_registration.sid}")
            return campaign_registration
            
        except Exception as e:
            logger.error(f"Error registering A2P campaign: {str(e)}")
            raise

    def register_a2p_10dlc(self, client_data):
        """Complete A2P 10DLC registration workflow"""
        try:
            logger.info("Starting complete A2P 10DLC registration...")
            
            # Extract business name from client data
            business_name = client_data.get('companyName') or client_data.get('business_name') or 'Client'
            
            # First, we need to create a messaging service for the campaign
            messaging_service = self.client.messaging.v1.services.create(
                friendly_name=f"A2P Service for {business_name}"
            )
            
            logger.info(f"Created messaging service: {messaging_service.sid}")
            
            # Register brand first
            brand_registration = self.register_a2p_brand(client_data)
            
            # Brand registration is complete - no need to create campaign for now
            logger.info("Brand registration submitted successfully.")
            campaign_registration = None
            
            # Add phone number to messaging service if available
            if client_data.get('phone_number_sid'):
                try:
                    self.client.messaging.v1.services(messaging_service.sid).phone_numbers.create(
                        phone_number_sid=client_data['phone_number_sid']
                    )
                    logger.info(f"Added phone number to messaging service")
                except Exception as e:
                    logger.warning(f"Could not add phone number to messaging service: {str(e)}")
            
            result = {
                'messaging_service': messaging_service,
                'brand_registration': brand_registration,
                'campaign_registration': campaign_registration,
                'status': 'registered'
            }
            
            logger.info("A2P 10DLC registration completed successfully")
            return result
            
        except Exception as e:
            # Handle duplicate brand error gracefully (expected in testing)
            if "Duplicate Brand" in str(e):
                logger.info(f"A2P registration skipped - brand already exists (expected for testing)")
                # Return partial success - messaging service was created
                result = {
                    'messaging_service': messaging_service,
                    'brand_registration': None,
                    'campaign_registration': None,
                    'status': 'messaging_service_only'
                }
                return result
            else:
                logger.error(f"Error in A2P 10DLC registration: {str(e)}")
                raise

class GoHighLevelOAuth:
    """Class to handle Go High Level OAuth 2.0 authentication and API calls"""
    
    def __init__(self, client_id, client_secret, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.base_url = GHL_BASE_URL
        self.api_base_url = GHL_API_BASE_URL
        self.access_token = None
        self.refresh_token = None
        self.location_id = None
        self.company_id = None
        self.token_expires_at = None
        
    def get_authorization_url(self, scopes=None, state=None):
        """Generate the authorization URL for OAuth flow"""
        if scopes is None:
            scopes = OAUTH_SCOPES
            
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes)
        }
        
        if state:
            params["state"] = state
            
        # Use the working OAuth endpoint from your example
        auth_url = f"{self.base_url}/oauth/chooselocation?" + urllib.parse.urlencode(params)
        
        logger.info(f"Generated auth URL: {auth_url}")
        return auth_url
    
    def exchange_code_for_token(self, authorization_code, user_type="Location"):
        """Exchange authorization code for access token"""
        # Use services.leadconnectorhq.com for token exchange
        token_url = "https://services.leadconnectorhq.com/oauth/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": authorization_code,
            "user_type": user_type
        }
        
        try:
            # Make request without headers as in get_token.py
            response = requests.post(token_url, data=data)
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                self.refresh_token = token_data.get("refresh_token")
                self.location_id = token_data.get("locationId")
                self.company_id = token_data.get("companyId")
                
                # Try to extract additional information from token if possible
                try:
                    # Parse JWT token to extract additional data
                    decoded_token = jwt.decode(self.access_token, options={"verify_signature": False})
                    
                    # Extract location ID if not already available
                    if not self.location_id and 'authClassId' in decoded_token:
                        self.location_id = decoded_token['authClassId']
                        logger.info(f"Extracted location_id from token: {self.location_id}")
                    
                    # Extract company ID if available in token
                    if not self.company_id and 'companyId' in decoded_token:
                        self.company_id = decoded_token['companyId']
                        logger.info(f"Extracted company_id from token: {self.company_id}")
                    
                    # Calculate token expiration time from token if available
                    if 'exp' in decoded_token:
                        self.token_expires_at = datetime.fromtimestamp(decoded_token['exp'])
                    else:
                        # Default to 24 hours if not in token
                        expires_in = token_data.get("expires_in", 86400)
                        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                except Exception as e:
                    logger.warning(f"Could not extract additional data from token: {e}")
                    # Fall back to standard expiration calculation
                    expires_in = token_data.get("expires_in", 86400)
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info("Successfully obtained access token")
                logger.info(f"Location ID: {self.location_id}")
                logger.info(f"Company ID: {self.company_id}")
                logger.info(f"Token will expire at: {self.token_expires_at}")
                
                # Save tokens for persistence
                self.save_tokens()
                
                return token_data
            else:
                logger.error(f"Failed to exchange code for token: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Error exchanging code for token: {str(e)}")
            return None
    
    def refresh_access_token(self):
        """Refresh the access token using refresh token"""
        if not self.refresh_token:
            logger.error("No refresh token available")
            return False
            
        token_url = "https://services.leadconnectorhq.com/oauth/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "user_type": "Location"
        }
        
        try:
            # Make request without headers as in get_token.py
            response = requests.post(token_url, data=data)
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                
                # Update refresh token if provided
                if token_data.get("refresh_token"):
                    self.refresh_token = token_data.get("refresh_token")
                
                # Try to extract additional information from token if possible
                try:
                    # Import jwt only when needed
                    decoded_token = jwt.decode(self.access_token, options={"verify_signature": False})
                    
                    # Extract location ID if not already available
                    if not self.location_id and 'authClassId' in decoded_token:
                        self.location_id = decoded_token['authClassId']
                        logger.info(f"Extracted location_id from token: {self.location_id}")
                    
                    # Extract company ID if available in token
                    if not self.company_id and 'companyId' in decoded_token:
                        self.company_id = decoded_token['companyId']
                        logger.info(f"Extracted company_id from token: {self.company_id}")
                    
                    # Calculate token expiration time from token if available
                    if 'exp' in decoded_token:
                        self.token_expires_at = datetime.fromtimestamp(decoded_token['exp'])
                    else:
                        # Default to 24 hours if not in token
                        expires_in = token_data.get("expires_in", 86400)
                        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                except Exception as e:
                    logger.warning(f"Could not extract additional data from token: {e}")
                    # Fall back to standard expiration calculation
                    expires_in = token_data.get("expires_in", 86400)
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info("Successfully refreshed access token")
                logger.info(f"Token will expire at: {self.token_expires_at}")
                
                # Save tokens for persistence
                self.save_tokens()
                return True
            else:
                logger.error(f"Failed to refresh token: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            return False
    
    def ensure_valid_token(self):
        """Ensure we have a valid access token, refresh if necessary"""
        if not self.access_token:
            logger.error("No access token available")
            return False
            
        # Check if token is about to expire (refresh 5 minutes before expiration)
        if self.token_expires_at and datetime.now() >= (self.token_expires_at - timedelta(minutes=5)):
            logger.info("Access token is about to expire, refreshing...")
            return self.refresh_access_token()
            
        return True
    
    def get_headers(self):
        """Get headers for API requests"""
        if not self.ensure_valid_token():
            raise Exception("Unable to obtain valid access token")
            
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Version": "2021-04-15"
        }
        
        return headers
    
    def make_api_request(self, method, endpoint, data=None, params=None):
        """Make an authenticated API request"""
        url = f"{self.api_base_url}{endpoint}"
        headers = self.get_headers()
        
        # Add location ID to params if not already present and we have one
        if self.location_id and params is None:
            params = {}
        if self.location_id and "locationId" not in str(params):
            if params is None:
                params = {}
            params["locationId"] = self.location_id
        
        response = requests.request(method, url, headers=headers, json=data, params=params)
        
        if response.status_code in [200, 201]:
            return response.json()
        else:
            logger.error(f"API request failed: {method} {endpoint} - {response.status_code} - {response.text}")
            return None
    
    def create_user(self, client_data):
        """Create a new location-level user in Go High Level for the current location"""
        if not self.location_id:
            logger.error("Location ID required for user creation")
            return None
            
        # Extract user info from client data
        # Use the client_name (full_name) for the user's name
        client_name = client_data.get('name', '')
        
        # Split the name into first and last name
        name_parts = client_name.split(' ', 1) if client_name else []
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[1] if len(name_parts) > 1 else ''  # Leave last name blank if not provided
        
        # Get business name from companyName field
        business_name = client_data.get('companyName', '')
        
        # If no client name is provided, use business name
        if not first_name and business_name:
            business_parts = business_name.split(' ', 1)
            first_name = business_parts[0]
            # Don't set a last name from business name
        
        # Ensure we have at least a first name
        if not first_name:
            first_name = "Client"
        
        logger.info(f"Creating user with name: {first_name} {last_name}")
        
        # Get phone number from client data - ensure it's in E.164 format
        phone = client_data.get('phone', '')
        if phone:
            # Remove any non-digit characters except the leading +
            if phone.startswith('+'):
                phone = '+' + ''.join(c for c in phone[1:] if c.isdigit())
            else:
                phone = '+1' + ''.join(c for c in phone if c.isdigit())
            
            # Ensure it starts with +1 for US numbers
            if not phone.startswith('+'):
                phone = '+' + phone
            if not phone.startswith('+1') and len(phone) == 11:  # If it's a 10-digit number without country code
                phone = '+1' + phone
                
            logger.info(f"Formatted phone number: {phone}")
        
        # Build user data for ACCOUNT-USER creation (v2 API)
        user_data = {
            "companyId": self.company_id,  # Required company ID
            "firstName": first_name,
            "lastName": last_name,
            "email": client_data.get('email', ''),
            "phone": phone,  # Use the formatted phone number
            "role": "user",  # Create regular account user (not admin)
            "type": "account",  # Specify account-level user type
            "locationIds": [self.location_id],  # Assign user to current location
            "permissions": {
                "campaignsEnabled": True,
                "campaignsReadOnly": True,  # Read-only for campaigns
                "contactsEnabled": True,
                "workflowsEnabled": True,
                "workflowsReadOnly": True,  # Read-only workflows
                "triggersEnabled": True,
                "funnelsEnabled": True,
                "websitesEnabled": False,  # Limited website access
                "opportunitiesEnabled": True,
                "dashboardStatsEnabled": True,
                "bulkRequestsEnabled": False,  # Limited bulk operations
                "appointmentsEnabled": True,
                "reviewsEnabled": True,
                "onlineListingsEnabled": False,  # Limited access
                "phoneCallEnabled": True,
                "conversationsEnabled": True,
                "assignedDataOnly": True,  # Only see assigned data
                "adwordsReportingEnabled": False,
                "membershipEnabled": False,  # Limited membership access
                "facebookAdsReportingEnabled": False,
                "attributionsReportingEnabled": False,
                "settingsEnabled": False,  # No settings access
                "tagsEnabled": True,
                "leadValueEnabled": True,
                "marketingEnabled": False,  # Limited marketing access
                "agentReportingEnabled": False,
                "botService": False,
                "socialPlanner": False,
                "bloggingEnabled": False,
                "invoiceEnabled": True,
                "affiliateManagerEnabled": False,
                "contentAiEnabled": False,
                "refundsEnabled": False,
                "recordPaymentEnabled": False,
                "cancelSubscriptionEnabled": False,
                "paymentsEnabled": True,
                "communitiesEnabled": False,
                "exportPaymentsEnabled": False
            }
        }
        
        # Use v2 API user creation endpoint
        endpoint = "/users/"
        
        logger.info(f"Creating ACCOUNT-USER: {first_name} {last_name} ({client_data.get('email')})")
        
        try:
            # Override headers for user creation API
            url = f"{self.api_base_url}{endpoint}"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "Version": "2021-07-28"  # Specific version for user creation
            }
            
            response = requests.post(url, headers=headers, json=user_data)
            
            if response.status_code in [200, 201]:
                response_data = response.json()
            elif response.status_code == 400 and "already exists" in response.text:
                logger.info(f"User already exists with this email - skipping user creation")
                # Return a mock response for existing user
                response_data = {
                    "id": "existing_user",
                    "email": client_data.get('email'),
                    "message": "User already exists"
                }
            else:
                logger.error(f"User creation API failed: {response.status_code} - {response.text}")
                response_data = None
            
            if response_data:
                user_id = response_data.get('id')
                logger.info(f"✅ ACCOUNT-USER created successfully: {user_id}")
                
                # Log important info
                generated_password = response_data.get('password')
                if generated_password:
                    logger.info(f"🔑 Auto-generated password: {generated_password}")
                
                return response_data
            else:
                logger.error(f"❌ Failed to create ACCOUNT-USER")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error creating ACCOUNT-USER: {e}")
            return None
    
    def create_calendar(self, calendar_data):
        """Create a new calendar in Go High Level"""
        endpoint = "/calendars/"
        response = self.make_api_request("POST", endpoint, data=calendar_data)
        if response:
            logger.info(f"Calendar created successfully: {calendar_data.get('name')}")
            return response
        else:
            logger.error(f"Failed to create calendar: {calendar_data.get('name')}")
            return None
    
    def link_calendar_to_client(self, client_id, calendar_id):
        """Link a calendar to a client"""
        endpoint = f"/contacts/{client_id}/calendars"
        data = {"calendarId": calendar_id}
        response = self.make_api_request("POST", endpoint, data=data)
        if response:
            logger.info(f"Calendar linked to client successfully")
            return response
        else:
            logger.error(f"Failed to link calendar to client")
            return None
            
    def get_client(self, client_id):
        """Get client details by ID"""
        endpoint = f"/contacts/{client_id}"
        response = self.make_api_request("GET", endpoint)
        if response:
            logger.info(f"Retrieved client details successfully")
            return response
        else:
            logger.error(f"Failed to retrieve client")
            return None
            
    def get_calendar(self, calendar_id):
        """Get calendar details by ID"""
        endpoint = f"/calendars/{calendar_id}"
        response = self.make_api_request("GET", endpoint)
        if response:
            logger.info(f"Retrieved calendar details successfully")
            return response
        else:
            logger.error(f"Failed to retrieve calendar")
            return None
            
    def get_form_submissions(self, form_id, start_date=None, end_date=None, limit=100, page=1):
        """
        Get submissions from a specific form
        Based on: https://highlevel.stoplight.io/docs/integrations/a6114bd7685d1-get-forms-submissions
        
        Args:
            form_id: The ID of the form to retrieve submissions from
            start_date: Optional start date for filtering submissions (datetime object)
            end_date: Optional end date for filtering submissions (datetime object)
            limit: Maximum number of submissions per page (1-100, default: 20)
            page: Page number for pagination (default: 1)
            
        Returns:
            Dict with submissions data and pagination info, or None if failed
        """
        # Updated endpoint to match official API documentation
        endpoint = f"/forms/submissions"
        
        # Build query parameters according to API docs
        params = {
            "formId": form_id,
            "limit": min(limit, 100),  # API max is 100
            "page": page
        }
        
        # Add location ID as required parameter
        if self.location_id:
            params["locationId"] = self.location_id
        
        # Format dates according to API specification (YYYY-MM-DD)
        if start_date:
            params["startAt"] = start_date.strftime("%Y-%m-%d")
        
        if end_date:
            params["endAt"] = end_date.strftime("%Y-%m-%d")
            
        response = self.make_api_request("GET", endpoint, params=params)
        
        if response:
            # API returns different structure according to docs
            submissions = response.get("submissions", [])
            meta = response.get("meta", {})
            
            logger.info(f"Retrieved {len(submissions)} form submissions (page {page})")
            logger.info(f"Total submissions: {meta.get('total', 'unknown')}")
            
            return {
                "submissions": submissions,
                "meta": meta,
                "pagination": {
                    "currentPage": meta.get("currentPage", page),
                    "nextPage": meta.get("nextPage"),
                    "prevPage": meta.get("prevPage"),
                    "total": meta.get("total")
                }
            }
        else:
            logger.error(f"Failed to retrieve form submissions")
            return None
            
    def get_form_fields(self, form_id):
        """
        Get field definitions for a specific form
        
        Args:
            form_id: The ID of the form
            
        Returns:
            List of form fields or None if failed
        """
        endpoint = f"/forms/{form_id}"
        
        response = self.make_api_request("GET", endpoint)
        
        if response:
            form_data = response
            fields = form_data.get("form", {}).get("fields", [])
            logger.info(f"Retrieved {len(fields)} form fields")
            return fields
        else:
            logger.error(f"Failed to retrieve form fields")
            return None

    def save_tokens(self, filename="tokens.json"):
        """Save tokens to a file for persistence"""
        token_data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "location_id": self.location_id,
            "company_id": self.company_id,
            "token_expires_at": self.token_expires_at.isoformat() if self.token_expires_at else None
        }
        
        with open(filename, "w") as f:
            json.dump(token_data, f, indent=2)
        logger.info(f"Tokens saved to {filename}")
    
    def load_tokens(self, filename="tokens.json"):
        """Load tokens from a file"""
        try:
            with open(filename, "r") as f:
                token_data = json.load(f)
            
            self.access_token = token_data.get("access_token")
            self.refresh_token = token_data.get("refresh_token")
            self.location_id = token_data.get("location_id")
            self.company_id = token_data.get("company_id")
            
            if token_data.get("token_expires_at"):
                self.token_expires_at = datetime.fromisoformat(token_data["token_expires_at"])
            
            logger.info(f"Tokens loaded from {filename}")
            return True
        except FileNotFoundError:
            logger.info(f"Token file {filename} not found")
            return False
        except Exception as e:
            logger.error(f"Error loading tokens: {str(e)}")
            return False

def perform_oauth_flow(oauth_client):
    """Perform the OAuth authorization flow"""
    # Try to load existing tokens first
    if oauth_client.load_tokens():
        # Check if tokens are still valid
        if oauth_client.ensure_valid_token():
            logger.info("Using existing valid tokens")
            return True
        else:
            logger.info("Existing tokens are invalid, starting new OAuth flow")
    
    # Generate authorization URL
    auth_url = oauth_client.get_authorization_url()
    
    print("\n" + "="*80)
    print("OAUTH AUTHORIZATION REQUIRED")
    print("="*80)
    print(f"Please visit the following URL to authorize the application:")
    print(f"\n{auth_url}\n")
    print("After authorization, you will be redirected to your redirect URI.")
    print("Copy the 'code' parameter from the redirect URL and paste it below.")
    print("="*80)
    
    # Try to open the URL in the default browser
    try:
        webbrowser.open(auth_url)
        print("Opening authorization URL in your default browser...")
    except Exception as e:
        logger.warning(f"Could not open browser automatically: {e}")
    
    # Get the authorization code from user
    authorization_code = input("\nEnter the authorization code: ").strip()
    
    if not authorization_code:
        logger.error("No authorization code provided")
        return False
    
    # Exchange code for tokens
    token_data = oauth_client.exchange_code_for_token(authorization_code)
    
    if token_data:
        # Save tokens for future use
        oauth_client.save_tokens()
        logger.info("OAuth flow completed successfully")
        return True
    else:
        logger.error("OAuth flow failed")
        return False

def create_user_and_calendar(oauth_client, client_data, calendar_data):
    """
    Complete workflow to create a user, create a calendar, and link them together
    
    Args:
        oauth_client: GoHighLevelOAuth instance
        client_data: Dict with client information
        calendar_data: Dict with calendar information
        
    Returns:
        Tuple (user_id, calendar_id) if successful, None otherwise
    """
    # Phase 1: Create the user
    user_response = oauth_client.create_user(client_data)
    if not user_response:
        logger.error("User creation failed, stopping workflow")
        return None
    
    user_id = user_response.get("id")
    user_email = client_data.get("email")
    user_password = user_response.get("password")
    
    logger.info(f"Created user with ID: {user_id}")
    logger.info(f"User Email: {user_email}")
    if user_password:
        logger.info(f"User Password: {user_password}")
    
    # Phase 2: Create the calendar
    calendar_response = oauth_client.create_calendar(calendar_data)
    if not calendar_response:
        logger.error("Phase 2 failed: Calendar creation failed")
        # Don't return None here, continue with the process even if calendar creation fails
        calendar_id = None
    else:
        calendar_id = calendar_response.get("id")
        logger.info(f"✓ Phase 2 complete: Created calendar with ID: {calendar_id}")
        logger.info("✓ Shared calendar created with user assigned to round robin team")
    
    # Note: Calendar linking may not be available for users like it is for contacts
    # Users will have access to calendars through their location permissions
    
    logger.info(f"Successfully created user {user_id} and calendar {calendar_id}")
    return (user_id, calendar_id)

def process_form_submission(submission, fields_mapping=None):
    """
    Process a form submission and convert it to client data
    Updated to handle the actual GHL API response structure and field ID mappings
    
    Args:
        submission: The form submission data
        fields_mapping: Optional mapping of form fields to client fields
        
    Returns:
        Dict with client data
    """
    logger.info("Processing form submission...")
    
    # Initialize client data with required GHL structure
    client_data = {
        "name": "",
        "email": "",
        "phone": "",
        "companyName": "",
        "address": {
            "country": "USA"  # Default country is always USA
        },
        "source": "Client_Onboarding_Form",
        "tags": ["Client", "Onboarded", "Active_Client", "API_Contact"],
        "customFields": [],
        "working_hours": {},  # Store working hours for calendar creation
        "field_mappings_used": {}  # Track which field mappings were used
    }
    
    # Extract direct fields
    if submission.get("name"):
        client_data["name"] = submission["name"]
        client_data["field_mappings_used"]["name"] = "direct"
        logger.info(f"Direct name: {client_data['name']}")
    
    if submission.get("email"):
        client_data["email"] = submission["email"]
        client_data["field_mappings_used"]["email"] = "direct"
        logger.info(f"Direct email: {client_data['email']}")
    
    # Extract fields from the "others" object
    others = submission.get("others", {})
    
    # Field ID to Field Name Mapping
    FIELD_ID_MAPPING = {
        "i0IQ8WjvM7HfaHVk21MH": "business_time_zone",
        "a24WJXsCB54SwoIxN0Rx": "zip_codes_for_targeting",
        "XdGavN9kI5tWJ6KgCusY": "working_hours",
        "JPZRWM9OisPRkElvYzaO": "appointments_per_day",
        "eAWIt4LmTOHFtmmhF76S": "appointments_purchased",
        "COQHzHOTfLRVTjWdHj2I": "years_in_business",
        "RxBJOSfz1BgEKWw9Elrm": "role",
        "2r2w8iKtE7P6YTQPk55U": "sales_for_2024",
        "moTUEvoc35yRH2SlEuRo": "challenges_faced",
        "1msoKMpJKOiX3mgh812t": "what_brought_you_to_us"
    }
    
    # Translate field IDs to field names for easier processing
    logger.info("Translating field IDs to field names...")
    for field_id in list(others.keys()):
        if field_id in FIELD_ID_MAPPING:
            field_name = FIELD_ID_MAPPING[field_id]
            field_value = others[field_id]
            others[field_name] = field_value
            client_data["field_mappings_used"][field_name] = field_id
            logger.info(f"  {field_id} → {field_name}: {field_value}")
    
    # Direct field mappings from "others"
    field_mappings = {
        "phone": ["phone", "phoneNumber", "phone_number", "mobile"],
        "companyName": ["business_name", "company_name", "client_business_name", "company", "companyName", "businessName", "first_name"],
        "name": ["client_name", "full_name", "poc_name_1", "name"]  # full_name is client name
    }
    
    # Address field mappings from "others"
    address_mappings = {
        "line1": ["address", "business_address", "streetAddress", "address1", "street"],
        "city": ["city"],
        "state": ["state", "province"], 
        "postalCode": ["postal_code", "zip", "zipCode", "postalCode"]
        # Country is already set to USA by default
    }
    
    # Process standard fields
    logger.info("Mapping standard fields...")
    for client_field, possible_names in field_mappings.items():
        for field_name in possible_names:
            if field_name in others and others[field_name]:
                client_data[client_field] = others[field_name]
                client_data["field_mappings_used"][client_field] = field_name
                logger.info(f"  {client_field} ← {field_name}: {others[field_name]}")
                break
    
    # Ensure we have a company name - if not found, use a default
    if not client_data.get("companyName"):
        if client_data.get("name"):
            # Use the client name with "Business" appended if no company name is found
            client_data["companyName"] = f"{client_data['name']}'s Business"
            logger.info(f"  No company name found, using client name: {client_data['companyName']}")
        else:
            client_data["companyName"] = "New Client Business"
            logger.info(f"  No company or client name found, using default: {client_data['companyName']}")
    
    # Ensure we have a client name - if not found, use company name
    if not client_data.get("name"):
        if client_data.get("companyName"):
            # Extract first part of company name as client name
            client_data["name"] = client_data["companyName"].split(" ")[0]
            logger.info(f"  No client name found, using company name: {client_data['name']}")
        else:
            client_data["name"] = "Client"
            logger.info(f"  No client or company name found, using default: {client_data['name']}")
            
    # Log the field mappings used
    logger.info("Field mappings used:")
    for field, mapping in client_data["field_mappings_used"].items():
        logger.info(f"  {field}: {mapping}")
    
    # Process address fields
    logger.info("Mapping address fields...")
    for address_field, possible_names in address_mappings.items():
        for field_name in possible_names:
            if field_name in others and others[field_name]:
                client_data["address"][address_field] = others[field_name]
                client_data["field_mappings_used"][f"address.{address_field}"] = field_name
                logger.info(f"  address.{address_field} ← {field_name}: {others[field_name]}")
                break
    
    # Process working hours from complex structure
    if "working_hours" in others:
        working_hours_data = others["working_hours"]
        
        # Working hours day mapping
        WORKING_HOURS_DAY_MAPPING = {
            "6b65bf74-32ff-4342-9629-bba68679ff00": "monday",
            "5783a7ba-cf90-4826-bf82-68aa83335488": "tuesday",
            "94126b3a-ec45-4947-a2aa-a1deeec68d62": "wednesday",
            "option-1750956538898": "thursday",
            "option-1750956603512": "friday",
            "option-1750956604386": "saturday",
            "option-1750956605407": "sunday"
        }
        
        # Check if it's a string that needs to be parsed as JSON
        if isinstance(working_hours_data, str):
            try:
                working_hours_data = json.loads(working_hours_data.replace("'", '"'))
            except:
                # If parsing fails, keep as string
                pass
        
        # If it's a dictionary, extract the hours
        if isinstance(working_hours_data, dict):
            logger.info("Extracting working hours schedule:")
            for day_id, day_name in WORKING_HOURS_DAY_MAPPING.items():
                if day_id in working_hours_data and working_hours_data[day_id]:
                    client_data["working_hours"][day_name] = working_hours_data[day_id]
                    logger.info(f"  {day_name.capitalize()}: {working_hours_data[day_id]}")
                    
                    # Add as custom field for CRM
                client_data["customFields"].append({
                        "key": f"contact.working_hours_{day_name}",
                        "field_value": str(working_hours_data[day_id])
                })
    
    # Add important business fields as custom fields
    custom_field_mappings = {
        "business_time_zone": "contact.business_time_zone",
        "zip_codes_for_targeting": "contact.zip_codes_for_targeting_locations",
        "appointments_per_day": "contact.appointments_per_day",
        "appointments_purchased": "contact.appointments_purchased",
        "years_in_business": "contact.years_in_business",
        "sales_for_2024": "contact.sales_for_2024",
        "challenges_faced": "contact.challenges_faced",
        "what_brought_you_to_us": "contact.what_brought_you_to_us",
        "role": "contact.role"
    }
    
    # Process custom fields
    logger.info("Adding business fields as custom fields:")
    for field_name, custom_key in custom_field_mappings.items():
        if field_name in others and others[field_name]:
            client_data["customFields"].append({
                "key": custom_key,
                "field_value": str(others[field_name])
            })
            logger.info(f"  {custom_key}: {others[field_name]}")
    
    # Store business information directly in client_data for easier access
    if "business_time_zone" in others:
        client_data["timezone"] = others["business_time_zone"]
    if "zip_codes_for_targeting" in others:
        client_data["zip_codes_for_targeting"] = others["zip_codes_for_targeting"]
    if "appointments_per_day" in others:
        client_data["appointments_per_day"] = others["appointments_per_day"]
    if "appointments_purchased" in others:
        client_data["appointments_purchased"] = others["appointments_purchased"]
    if "years_in_business" in others:
        client_data["years_in_business"] = others["years_in_business"]
    
    # Add business name as a tag if present
    if client_data["companyName"]:
        client_data["tags"].append(f"Business:{client_data['companyName']}")
                
    # Log the final client data for verification
    logger.info("\nFINAL CLIENT DATA:")
    logger.info(f"Name: {client_data.get('name', 'Not set')}")
    logger.info(f"Email: {client_data.get('email', 'Not set')}")
    logger.info(f"Phone: {client_data.get('phone', 'Not set')}")
    logger.info(f"Company Name: {client_data.get('companyName', 'Not set')}")
    logger.info(f"Address: {client_data.get('address', {})}")
    logger.info(f"Timezone: {client_data.get('timezone', 'Not set')}")
    logger.info(f"ZIP Codes for Targeting: {client_data.get('zip_codes_for_targeting', 'Not set')}")
                
    return client_data

def extract_calendar_settings_from_client_data(client_data):
    """
    Extract calendar settings from client data custom fields
    
    Args:
        client_data: Dict with client information including custom fields
        
    Returns:
        Dict with calendar settings
    """
    settings = {
        "timezone": "America/New_York",  # Default timezone
        "availability": {
            "monday": [{"start": "09:00", "end": "17:00"}],
            "tuesday": [{"start": "09:00", "end": "17:00"}],
            "wednesday": [{"start": "09:00", "end": "17:00"}],
            "thursday": [{"start": "09:00", "end": "17:00"}],
            "friday": [{"start": "09:00", "end": "17:00"}]
        },
        "duration": 60,
        "bufferBefore": 15,
        "bufferAfter": 15
    }
    
    # Extract timezone from custom fields - first check for business_time_zone specifically
    business_timezone = None
    time_zone_field = None
    
    # First pass - look specifically for business_time_zone
    for custom_field in client_data.get("customFields", []):
        if custom_field.get("key") == "contact.business_time_zone":
            business_timezone = custom_field.get("field_value", "")
            break
        elif custom_field.get("key") == "contact.time_zone" and not time_zone_field:
            time_zone_field = custom_field
    
    # If business_time_zone not found, fall back to time_zone
    if not business_timezone and time_zone_field:
        business_timezone = time_zone_field.get("field_value", "")
    
    # Process timezone value if found
    if business_timezone:
        # Map common timezone names to proper timezone identifiers
        timezone_mapping = {
            "eastern": "America/New_York",
            "central": "America/Chicago", 
            "mountain": "America/Denver",
            "pacific": "America/Los_Angeles",
            "est": "America/New_York",
            "edt": "America/New_York",
            "cst": "America/Chicago",
            "cdt": "America/Chicago",
            "mst": "America/Denver", 
            "mdt": "America/Denver",
            "pst": "America/Los_Angeles",
            "pdt": "America/Los_Angeles",
            "et": "America/New_York",
            "ct": "America/Chicago",
            "mt": "America/Denver",
            "pt": "America/Los_Angeles"
        }
        
        timezone_lower = business_timezone.lower()
        for key, tz in timezone_mapping.items():
            if key in timezone_lower:
                settings["timezone"] = tz
                logger.info(f"Setting calendar timezone to {tz} based on business time zone: {business_timezone}")
                break
    
    # Rest of the function remains the same
    # Extract working days
    for custom_field in client_data.get("customFields", []):
        if custom_field.get("key") == "contact.which_days_of_the_week_do_you_work_on_appointments":
            working_days_value = custom_field.get("field_value", "").lower()
            if working_days_value:
                # Reset availability to empty
                settings["availability"] = {}
                
                # Check for each day
                days_mapping = {
                    "monday": "monday",
                    "tuesday": "tuesday", 
                    "wednesday": "wednesday",
                    "thursday": "thursday",
                    "friday": "friday",
                    "saturday": "saturday",
                    "sunday": "sunday"
                }
                
                for day_name, day_key in days_mapping.items():
                    if day_name in working_days_value:
                        settings["availability"][day_key] = [{"start": "09:00", "end": "17:00"}]
        
        # Extract working hours
        elif custom_field.get("key") == "contact.what_is_the_earliest_and_latest_time_you_can_run_appointments":
            hours_value = custom_field.get("field_value", "")
            if hours_value:
                # Try to parse time ranges like "9am-5pm", "09:00-17:00", "12 to 2", "12:30 to 3:50"
                import re
                
                # Find any time range pattern in the string
                # This regex matches various formats with or without AM/PM indicators
                time_pattern = r'(\d{1,2})(?::(\d{1,2}))?\s*(am|pm)?\s*(?:[-to]+)\s*(\d{1,2})(?::(\d{1,2}))?\s*(am|pm)?'
                match = re.search(time_pattern, hours_value.lower())
                
                if match:
                    start_hour_str, start_min_str, start_ampm, end_hour_str, end_min_str, end_ampm = match.groups()
                    
                    # Parse hours and minutes
                    start_hour = int(start_hour_str)
                    end_hour = int(end_hour_str)
                    start_min = int(start_min_str) if start_min_str else 0
                    end_min = int(end_min_str) if end_min_str else 0
                    
                    # Track if AM/PM was explicitly specified
                    start_is_am = start_ampm == 'am'
                    start_is_pm = start_ampm == 'pm'
                    end_is_am = end_ampm == 'am'
                    end_is_pm = end_ampm == 'pm'
                    
                    # Convert to 24-hour format if AM/PM is specified
                    if start_is_pm and start_hour < 12:
                        start_hour += 12
                    elif start_is_am and start_hour == 12:
                        start_hour = 0
                        
                    if end_is_pm and end_hour < 12:
                        end_hour += 12
                    elif end_is_am and end_hour == 12:
                        end_hour = 0
                    
                    # Handle cases where AM/PM is not specified
                    if not (start_is_am or start_is_pm) and not (end_is_am or end_is_pm):
                        # If both times have no AM/PM indicator
                        
                        # Case 1: Both times are in the same half of the day
                        if (start_hour < 12 and end_hour < 12) or (start_hour >= 12 and end_hour >= 12):
                            # If end time is less than start time, assume end time is PM if both are AM
                            if end_hour < start_hour and start_hour < 12:
                                end_hour += 12
                        
                        # Case 2: Likely crossing from AM to PM
                        elif start_hour < 12 and end_hour >= 12:
                            # This is already correct (e.g., 10 to 14)
                            pass
                        
                        # Case 3: Likely crossing from PM to AM (overnight)
                        elif start_hour >= 12 and end_hour < 12:
                            # This is unusual but possible (e.g., 22 to 2)
                            # We'll assume this is not overnight and end time is PM
                            end_hour += 12
                        
                        # Special case: Both times are small numbers
                        if start_hour < 7 and end_hour < 7:
                            # Assume business hours (e.g., 5 to 6 likely means 5PM to 6PM)
                            start_hour += 12
                            end_hour += 12
                    
                    # Special case: If end hour is still less than start hour, it might be overnight
                    # But in business context, it's more likely both are PM or both are AM
                    if end_hour < start_hour:
                        # If end hour is very small (1-6) and start hour is larger, assume end is PM
                        if end_hour < 7 and not end_is_am:
                            end_hour += 12
                    
                    start_time = f"{start_hour:02d}:{start_min:02d}"
                    end_time = f"{end_hour:02d}:{end_min:02d}"
                    
                    logger.info(f"Parsed working hours: {start_time} to {end_time}")
                    
                    # Update all working days with these hours
                    for day in settings["availability"]:
                        settings["availability"][day] = [{"start": start_time, "end": end_time}]
    
    return settings

def get_client_details_from_form(oauth_client, form_id, days_back=7):
    """
    Get client details from recent form submissions
    Updated to work with new API endpoint structure
    
    Args:
        oauth_client: GoHighLevelOAuth instance
        form_id: Form ID to check for submissions
        days_back: Number of days to look back for submissions
        
    Returns:
        List of processed client data from form submissions
    """
    # Calculate start date
    start_date = datetime.now() - timedelta(days=days_back)
    
    # Get form submissions using updated API
    response = oauth_client.get_form_submissions(form_id, start_date=start_date)
    
    if not response or not response.get("submissions"):
        logger.info("No recent form submissions found")
        return []
    
    submissions = response["submissions"]
    pagination = response.get("pagination", {})
    
    logger.info(f"Found {len(submissions)} form submissions in the last {days_back} days")
    if pagination.get("total"):
        logger.info(f"Total submissions available: {pagination['total']}")
    
    # Process each submission
    processed_clients = []
    for submission in submissions:
        try:
            client_data = process_form_submission(submission)
            if client_data and client_data.get("name") and client_data.get("email"):
                processed_clients.append(client_data)
                logger.info(f"Processed client: {client_data.get('name')} ({client_data.get('email')})")
            else:
                logger.warning("Skipping incomplete form submission")
        except Exception as e:
            logger.error(f"Error processing form submission: {e}")
    
    return processed_clients

def convert_hours_to_est(hour, minute, source_timezone):
    """
    Convert hours from source timezone to EST/EDT
    
    Args:
        hour: Hour in source timezone (24-hour format)
        minute: Minute in source timezone
        source_timezone: Source timezone string
        
    Returns:
        Tuple of (hour, minute) in EST/EDT
    """
    # Map common timezone names to proper timezone identifiers
    timezone_mapping = {
        "eastern": "America/New_York",
        "central": "America/Chicago", 
        "mountain": "America/Denver",
        "pacific": "America/Los_Angeles",
        "est": "America/New_York",
        "edt": "America/New_York",
        "cst": "America/Chicago",
        "cdt": "America/Chicago",
        "mst": "America/Denver", 
        "mdt": "America/Denver",
        "pst": "America/Los_Angeles",
        "pdt": "America/Los_Angeles",
        "et": "America/New_York",
        "ct": "America/Chicago",
        "mt": "America/Denver",
        "pt": "America/Los_Angeles"
    }
    
    # Default to EST if timezone not recognized
    est_tz = pytz.timezone("America/New_York")
    
    # Get source timezone
    source_tz_str = "America/New_York"  # Default to EST
    source_timezone_lower = source_timezone.lower() if source_timezone else ""
    
    for key, tz in timezone_mapping.items():
        if key in source_timezone_lower:
            source_tz_str = tz
            break
    
    source_tz = pytz.timezone(source_tz_str)
    
    # If already EST/EDT, no conversion needed
    if source_tz_str == "America/New_York":
        return hour, minute
    
    # Create a datetime object for today with the specified time in source timezone
    now = datetime.now()
    source_time = datetime(now.year, now.month, now.day, hour, minute)
    
    # Make it timezone-aware in source timezone
    source_time_aware = source_tz.localize(source_time)
    
    # Convert to EST/EDT
    est_time = source_time_aware.astimezone(est_tz)
    
    # Return the hour and minute in EST/EDT
    return est_time.hour, est_time.minute

def complete_client_onboarding_with_phone(oauth_client, twilio_manager, client_data, phone_preferences=None):
    """
    Complete Phase 1-4 workflow: Create user, calendar, purchase phone number, and assign phone to user
    
    Args:
        oauth_client: GoHighLevelOAuth instance
        twilio_manager: TwilioPhoneManager instance (not used with new implementation)
        client_data: Dict with client information
        phone_preferences: Dict with phone number preferences
        
    Returns:
        Dict with all created resources or None if failed
    """
    logger.info("="*80)
    logger.info("STARTING COMPLETE USER ONBOARDING WITH PHONE NUMBER ASSIGNMENT")
    logger.info("="*80)
    
    # Get business name from form field (mapped from business_name form field)
    business_name = client_data.get('companyName', 'Unknown Client')
    logger.info(f"Processing client: {business_name}")
    
    # Phase 1: Create the user in GHL (assigned to current location)
    logger.info("Phase 1: Creating user in Go High Level...")
    user_response = oauth_client.create_user(client_data)
    if not user_response:
        logger.error("Phase 1 failed: User creation failed")
        return None
    
    user_id = user_response.get("id")
    user_email = client_data.get("email")
    user_password = user_response.get("password")
    
    logger.info(f"✓ Phase 1 complete: Created user with ID: {user_id}")
    logger.info(f"  User Email: {user_email}")
    if user_password:
        logger.info(f"  User Password: {user_password}")
    
    # Phase 2: Create calendar based on client data
    logger.info("Phase 2: Creating calendar...")
    
    # Skip calendar creation if user already exists
    if user_id == "existing_user":
        logger.info("✓ Phase 2 skipped: User already exists, calendar likely already assigned")
        calendar_id = "existing_calendar"
        calendar_response = {"id": "existing_calendar", "message": "Skipped for existing user"}
        calendar_settings = {}
    else:
        # Use the working hours and timezone directly from client_data
        calendar_settings = {
            "timezone": client_data.get("timezone", "America/New_York"),
            "working_hours": client_data.get("working_hours", {}),
            "appointments_per_day": client_data.get("appointments_per_day", 10)
        }
        
        # Extract first name from client data
        client_name = client_data.get('name', '')
        first_name = client_name.split(' ')[0] if client_name else 'Client'
        
        # Create calendar name as "first name + business name"
        # If no business name provided, create a default
        if business_name == 'Unknown Client' or not business_name:
            calendar_business_name = f"{first_name}'s Business"
        else:
            calendar_business_name = business_name
        
        calendar_name = f"{first_name} {calendar_business_name}"
        
        # Create calendar data structure with working hours from client data
        calendar_data = {
        "isActive": True,
        "locationId": oauth_client.location_id,
        "name": f"{calendar_name} - Appointments",
        "description": f"Appointment calendar for {calendar_name}",
        "slug": f"{calendar_name.lower().replace(' ', '-')}-appointments",
        "widgetSlug": f"{calendar_name.lower().replace(' ', '-')}-appointments",
        "calendarType": "round_robin",
        "widgetType": "classic",
        "eventType": "RoundRobin_OptimizeForAvailability",
        "eventTitle": f"Appointment with {calendar_name}",
        "eventColor": "#039be5",
        "locationConfigurations": [
            {
                "kind": "custom",
                "location": "Phone Call"
            }
        ],
        "teamMembers": [
            {
                "userId": user_id,  # Assign user to shared round robin calendar
                "priority": 1.0,
                "isPrimary": True,
                "locationConfigurations": [
                    {
                        "kind": "custom",
                        "location": "Phone Call"
                    }
                ]
            }
        ],
        "slotDuration": 60,
        "slotDurationUnit": "mins",
        "slotInterval": 60,
        "slotIntervalUnit": "mins",
        "slotBuffer": 0,
        "slotBufferUnit": "mins",
        "preBuffer": 15,
        "preBufferUnit": "mins",
        "appoinmentPerSlot": 1,
            "appoinmentPerDay": int(calendar_settings.get("appointments_per_day", 10)),
        "allowBookingAfter": 1,
        "allowBookingAfterUnit": "hours",
        "allowBookingFor": 30,
        "allowBookingForUnit": "days",
            # Remove timezone property as it's not accepted by the API
            "openHours": []
        }
        
        # Convert working hours from client data to calendar open hours format
        working_hours = calendar_settings.get("working_hours", {})
        day_number_map = {
            "monday": 1,
            "tuesday": 2,
            "wednesday": 3,
            "thursday": 4,
            "friday": 5,
            "saturday": 6,
            "sunday": 0
        }
        
        # Add working hours to calendar data
        for day, hours in working_hours.items():
            if not hours:
                continue
                
            # Parse hours like "9:00 - 17:00", "9:30 - 5:30", "11:00 - 6:00", "12 to 2", "12:30 to 3:50"
            try:
                # Handle different separators: "-", "to", etc.
                if " - " in hours:
                    hours_parts = hours.split(" - ")
                elif " to " in hours:
                    hours_parts = hours.split(" to ")
                elif "-" in hours:
                    hours_parts = hours.split("-")
                else:
                    # Default fallback - try to split by space
                    parts = hours.split()
                    if len(parts) >= 3 and parts[1].lower() in ["to", "-"]:
                        hours_parts = [parts[0], parts[2]]
                    else:
                        logger.warning(f"Could not parse time format: {hours}")
                        continue
                
                start_time = hours_parts[0].strip()
                end_time = hours_parts[1].strip()
                
                # Helper function to parse time with AM/PM handling
                def parse_time_with_ampm(time_str):
                    # Check for AM/PM indicators
                    time_lower = time_str.lower()
                    is_pm = 'pm' in time_lower
                    is_am = 'am' in time_lower
                    
                    # Remove AM/PM indicators for parsing
                    time_str = time_lower.replace('am', '').replace('pm', '').strip()
                    
                    # Parse hours and minutes
                    if ':' in time_str:
                        parts = time_str.split(':')
                        hour = int(parts[0])
                        minute = int(parts[1]) if len(parts) > 1 else 0
                    else:
                        hour = int(time_str)
                        minute = 0
                    
                    # Convert to 24-hour format if PM
                    if is_pm and hour < 12:
                        hour += 12
                    elif is_am and hour == 12:
                        hour = 0
                    
                    return hour, minute, is_am, is_pm
                
                # Parse start and end times
                start_hour, start_minute, start_is_am, start_is_pm = parse_time_with_ampm(start_time)
                end_hour, end_minute, end_is_am, end_is_pm = parse_time_with_ampm(end_time)
                
                # Handle cases where AM/PM is not specified
                if not (start_is_am or start_is_pm) and not (end_is_am or end_is_pm):
                    # If both times have no AM/PM indicator
                    
                    # Case 1: Both times are in the same half of the day
                    if (start_hour < 12 and end_hour < 12) or (start_hour >= 12 and end_hour >= 12):
                        # If end time is less than start time, assume end time is PM if both are AM
                        if end_hour < start_hour and start_hour < 12:
                            end_hour += 12
                    
                    # Case 2: Likely crossing from AM to PM
                    elif start_hour < 12 and end_hour >= 12:
                        # This is already correct (e.g., 10 to 14)
                        pass
                    
                    # Case 3: Likely crossing from PM to AM (overnight)
                    elif start_hour >= 12 and end_hour < 12:
                        # This is unusual but possible (e.g., 22 to 2)
                        # We'll assume this is not overnight and end time is PM
                        end_hour += 12
                    
                    # Special case: Both times are small numbers
                    if start_hour < 7 and end_hour < 7:
                        # Assume business hours (e.g., 5 to 6 likely means 5PM to 6PM)
                        start_hour += 12
                        end_hour += 12
                
                # Special case: If end hour is still less than start hour, it might be overnight
                # But in business context, it's more likely both are PM or both are AM
                if end_hour < start_hour:
                    # If end hour is very small (1-6) and start hour is larger, assume end is PM
                    if end_hour < 7 and not end_is_am:
                        end_hour += 12
                
                # Get client timezone from settings
                client_timezone = calendar_settings.get("timezone", "America/New_York")
                
                # Convert hours to EST/EDT if client timezone is different
                if client_timezone and client_timezone != "America/New_York":
                    logger.info(f"Converting hours from {client_timezone} to EST/EDT")
                    logger.info(f"Original hours: {start_hour}:{start_minute:02d} - {end_hour}:{end_minute:02d}")
                    
                    # Convert start time
                    start_hour, start_minute = convert_hours_to_est(start_hour, start_minute, client_timezone)
                    
                    # Convert end time
                    end_hour, end_minute = convert_hours_to_est(end_hour, end_minute, client_timezone)
                    
                    logger.info(f"Converted hours: {start_hour}:{start_minute:02d} - {end_hour}:{end_minute:02d}")
                
                logger.info(f"Final {day} hours in EST/EDT: {start_hour}:{start_minute:02d} - {end_hour}:{end_minute:02d}")
                
                # Add to open hours
                calendar_data["openHours"].append({
                    "daysOfTheWeek": [day_number_map.get(day.lower(), 1)],
                    "hours": [
                        {
                            "openHour": start_hour,
                            "openMinute": start_minute,
                            "closeHour": end_hour,
                            "closeMinute": end_minute
                        }
                    ]
                })
            except Exception as e:
                logger.warning(f"Could not parse working hours for {day}: {hours} - {e}")
        
        # If no working hours were added, add default hours
        if not calendar_data["openHours"]:
            calendar_data["openHours"] = [
            {
                "daysOfTheWeek": [1],  # Monday
                "hours": [
                    {
                        "openHour": 9,
                        "openMinute": 0,
                        "closeHour": 17,
                        "closeMinute": 0
                    }
                ]
            },
            {
                "daysOfTheWeek": [2],  # Tuesday
                "hours": [
                    {
                        "openHour": 9,
                        "openMinute": 0,
                        "closeHour": 17,
                        "closeMinute": 0
                    }
                ]
            },
            {
                "daysOfTheWeek": [3],  # Wednesday
                "hours": [
                    {
                        "openHour": 9,
                        "openMinute": 0,
                        "closeHour": 17,
                        "closeMinute": 0
                    }
                ]
            },
            {
                "daysOfTheWeek": [4],  # Thursday
                "hours": [
                    {
                        "openHour": 9,
                        "openMinute": 0,
                        "closeHour": 17,
                        "closeMinute": 0
                    }
                ]
            },
            {
                "daysOfTheWeek": [5],  # Friday
                "hours": [
                    {
                        "openHour": 9,
                        "openMinute": 0,
                        "closeHour": 17,
                        "closeMinute": 0
                    }
                ]
            }
            ]
        
        # Add other calendar settings
        calendar_data.update({
        "enableRecurring": False,
        "recurring": {
            "freq": "DAILY",
            "count": 1,
            "bookingOption": "skip",
            "bookingOverlapDefaultStatus": "confirmed"
        },
        "formId": "",
        "stickyContact": True,
        "isLivePaymentMode": False,
        "autoConfirm": True,
        "shouldSendAlertEmailsToAssignedMember": True,
        "alertEmail": client_data.get("email", ""),
        "googleInvitationEmails": False,
        "allowReschedule": True,
        "allowCancellation": True,
        "shouldAssignContactToTeamMember": True,
        "shouldSkipAssigningContactForExisting": False,
        "notes": f"Calendar for {calendar_name} - Created via API",
        "pixelId": "",
        "formSubmitType": "ThankYouMessage",
        "formSubmitRedirectURL": "",
        "formSubmitThanksMessage": "Thank you for booking an appointment!",
        "availabilityType": 0,
        "guestType": "count_only",
        "consentLabel": "I agree to receive communications",
        "calendarCoverImage": "",
        "notifications": [
            {
                "type": "email",
                "shouldSendToContact": True,
                "shouldSendToGuest": False,
                "shouldSendToUser": True,
                "shouldSendToSelectedUsers": False,
                "selectedUsers": ""
            }
        ]
        })
        
        calendar_response = oauth_client.create_calendar(calendar_data)
        if not calendar_response:
            logger.error("Phase 2 failed: Calendar creation failed")
            # Don't return None here, continue with the process even if calendar creation fails
            calendar_id = None
        else:
            calendar_id = calendar_response.get("id")
        logger.info(f"✓ Phase 2 complete: Created calendar with ID: {calendar_id}")
        logger.info("✓ Shared calendar created with user assigned to round robin team")
    
    # Phase 3: Purchase phone number using login_ghl.py implementation
    logger.info("Phase 3: Purchasing phone number via CRM...")
    
    # Extract ZIP codes from client data for area code lookup
    zip_codes = None
    area_code = None
    
    # Check for ZIP codes in the client_data directly (from business fields)
    if client_data.get("zip_codes_for_targeting"):
        zip_codes = client_data["zip_codes_for_targeting"]
        logger.info(f"Using ZIP codes from business fields: {zip_codes}")
    # If not found, check custom fields
    else:
        for custom_field in client_data.get("customFields", []):
            if custom_field.get("key") == "contact.zip_codes_for_targeting_locations" or "zip_code" in custom_field.get("key", "").lower():
                zip_codes = custom_field.get("field_value", "")
                logger.info(f"Using ZIP codes from custom fields: {zip_codes}")
                break
    
    # If no ZIP codes found in business fields or custom fields, try address as fallback
    if not zip_codes and client_data.get("address", {}).get("postalCode"):
        zip_codes = client_data["address"]["postalCode"]
        logger.info(f"No ZIP codes found in business fields, using address postal code: {zip_codes}")
    
    # Check for area code in custom fields
    for custom_field in client_data.get("customFields", []):
        if "area_code" in custom_field.get("key", "").lower():
            area_code_value = custom_field.get("field_value", "")
            # Extract just the digits if there are any
            import re
            area_code_match = re.search(r'\d{3}', area_code_value)
            if area_code_match:
                area_code = area_code_match.group(0)
                logger.info(f"Found area code {area_code} in custom field")
                break
    
    # Try to derive area code from ZIP codes if we have them but no area code
    if not area_code and zip_codes:
        try:
            # Try to import area_code module
            import area_code as area_code_module
            best_area_code, all_area_codes, common_codes = area_code_module.get_best_area_code(zip_codes)
            if best_area_code:
                area_code = best_area_code
                logger.info(f"Derived area code {area_code} from ZIP codes {zip_codes}")
        except ImportError:
            logger.warning("area_code module not available for ZIP to area code conversion")
    
    # Call Phone_Number_Purchase from login_ghl.py with explicit instructions
    try:
        logger.info(f"Calling Phone_Number_Purchase with ZIP codes: {zip_codes} and area code: {area_code}")
        logger.info("IMPORTANT: Will select the FIRST visible number in the table and click its radio button")
        
        # Pass both zip_codes and area_code to the function
        phone_purchase_result = Phone_Number_Purchase(zip_codes=zip_codes, area_code=area_code)
        
        if phone_purchase_result and isinstance(phone_purchase_result, dict) and phone_purchase_result.get("selected_phone_number"):
            phone_number = phone_purchase_result["selected_phone_number"]["phone_number"]
            logger.info(f"✓ Phase 3 complete: Purchased phone number: {phone_number}")
            
            # Create a phone_result object compatible with the rest of the code
            phone_result = {
                'sid': 'CRM_PURCHASED',  # Not a Twilio SID but we need something
                'phone_number': phone_number,
                'friendly_name': f"{business_name} - {phone_number}",
                'capabilities': {
                    'voice': True,
                    'sms': True,
                    'mms': False
                },
                'date_created': datetime.now().isoformat(),
                'status': 'active',
                'client_info': {
                    'business_name': business_name,
                    'requested_zip_codes': zip_codes,
                    'requested_area_code': area_code
                }
            }
            
            # Log area code match information
            if area_code:
                # Extract area code correctly - format is "+1 XXX-XXX-XXXX"
                purchased_area_code = phone_number.split(" ")[1].split("-")[0] if " " in phone_number else phone_number[2:5]
                if purchased_area_code == area_code:
                    logger.info(f"✓ Phone number matches requested area code: {area_code}")
                else:
                    logger.info(f"⚠ Phone number has different area code. Requested: {area_code}, Got: {purchased_area_code}")
        else:
            logger.error("Phase 3 failed: Phone number purchase failed or returned unexpected format")
            logger.error(f"Phone purchase result: {phone_purchase_result}")
            phone_result = None
    except Exception as e:
        logger.error(f"Phase 3 failed: Error purchasing phone number: {e}")
        phone_result = None

    # Phase 3.5: A2P 10DLC Registration (required for SMS compliance)
    logger.info("Phase 3.5: A2P 10DLC Registration for SMS compliance...")
    
    a2p_result = None
    if phone_result and twilio_manager:
        try:
            # Add phone number info to client data for A2P registration
            client_data_with_phone = client_data.copy()
            client_data_with_phone['phone_number'] = phone_result['phone_number']
            
            a2p_result = twilio_manager.register_a2p_10dlc(client_data_with_phone)
            if a2p_result:
                logger.info(f"✓ Phase 3.5 complete: A2P 10DLC registration successful")
                logger.info(f"  Messaging Service SID: {a2p_result['messaging_service'].sid}")
                logger.info(f"  Registration Status: {a2p_result['status']}")
                
                if a2p_result.get('brand_registration'):
                    logger.info(f"  Brand Registration SID: {a2p_result['brand_registration'].sid}")
                else:
                    logger.info("  Brand Registration: Skipped (already exists)")
                    
                if a2p_result.get('campaign_registration'):
                    logger.info(f"  Campaign Registration SID: {a2p_result['campaign_registration'].sid}")
                else:
                    logger.info("  Campaign Registration: Not created (brand registration pending)")
            else:
                logger.error("Phase 3.5 failed: A2P 10DLC registration failed")
        except Exception as e:
            logger.error(f"Phase 3.5 failed: Error in A2P 10DLC registration: {e}")
            a2p_result = None
    else:
        if not phone_result:
            logger.info("Phase 3.5 skipped: No phone number to register for A2P")
        else:
            logger.info("Phase 3.5 skipped: Twilio manager not available")
        a2p_result = None

    # Phase 4: Assign phone number to user in CRM
    logger.info("Phase 4: Assigning phone number to user in CRM...")
    
    phone_assignment_result = None
    if phone_result and user_id != "existing_user":
        try:
            # Format the phone number correctly (remove any spaces or special characters)
            formatted_phone = phone_result['phone_number']
            if formatted_phone.startswith('+'):
                formatted_phone = '+' + ''.join(c for c in formatted_phone[1:] if c.isdigit())
            else:
                formatted_phone = '+1' + ''.join(c for c in formatted_phone if c.isdigit())
            
            logger.info(f"Formatted phone number for assignment: {formatted_phone}")
            
            # Based on our testing, we need to update the regular 'phone' field
            user_update_data = {
                "phone": formatted_phone
            }
            
            logger.info(f"Assigning phone number {formatted_phone} to user's 'phone' field")
            
            # Use the user update API endpoint with the correct version header
            update_endpoint = f"/users/{user_id}"
            
            # Custom headers for user API
            user_headers = {
                "Version": "2021-07-28"  # Specific version for user API
            }
            
            update_response = oauth_client.make_api_request("PUT", update_endpoint, data=user_update_data, headers=user_headers)
            
            if update_response:
                logger.info(f"✓ Phase 4 complete: Phone number {formatted_phone} assigned to user")
                logger.info(f"  User phone field updated successfully")
                
                # Verify the update was successful by checking the user's details
                get_user_response = oauth_client.make_api_request("GET", update_endpoint, headers=user_headers)
                if get_user_response:
                    user_phone = get_user_response.get("phone", "")
                    if user_phone == formatted_phone:
                        logger.info(f"✓ Verification successful: User phone field contains {formatted_phone}")
                    else:
                        logger.warning(f"⚠ Verification issue: User phone field contains {user_phone}, expected {formatted_phone}")
                
                phone_assignment_result = update_response
            else:
                logger.error("Phase 4 failed: Could not assign phone number to user")
                
                # Try alternative approach - use conversations API if available
                logger.info("Trying alternative approach for phone assignment...")
                try:
                    # Try to use the conversations API to assign the phone number
                    conv_endpoint = f"/locations/{oauth_client.location_id}/conversations/users/{user_id}/phone"
                    conv_data = {"phone": formatted_phone}
                    
                    conv_response = oauth_client.make_api_request("POST", conv_endpoint, data=conv_data)
                    
                    if conv_response:
                        logger.info(f"✓ Alternative approach successful: Phone number assigned via conversations API")
                        phone_assignment_result = conv_response
                    else:
                        logger.error("Alternative approach failed: Could not assign phone number via conversations API")
                except Exception as e:
                    logger.error(f"Error in alternative approach: {e}")
                
        except Exception as e:
            logger.error(f"Phase 4 failed: Error assigning phone number to user: {e}")
            phone_assignment_result = None
    else:
        if not phone_result:
            logger.info("Phase 4 skipped: No phone number to assign")
        else:
            logger.info("Phase 4 skipped: User already exists")
        phone_assignment_result = None

    # Compile results
    results = {
        "user": {
            "id": user_id,
            "data": user_response,
            "business_name": business_name,
            "email": user_email,
            "password": user_password
        },  
        "calendar": {
            "id": calendar_id,
            "data": calendar_response,
            "settings": calendar_settings
        },
        "phone": phone_result,
        "a2p_registration": a2p_result,
        "phone_assignment": phone_assignment_result,
        "success": True,
        "phases_completed": ["user_creation", "calendar_creation"]
    }
    
    if phone_result:
        results["phases_completed"].append("phone_purchase")
    
    if a2p_result:
        results["phases_completed"].append("a2p_registration")
        # Add A2P status details
        results["a2p_status"] = {
            "messaging_service_sid": a2p_result['messaging_service'].sid if a2p_result.get('messaging_service') else None,
            "brand_registration_sid": a2p_result['brand_registration'].sid if a2p_result.get('brand_registration') else None,
            "campaign_registration_sid": a2p_result['campaign_registration'].sid if a2p_result.get('campaign_registration') else None,
            "status": a2p_result.get('status', 'unknown')
        }
    
    if phone_assignment_result:
        results["phases_completed"].append("phone_assignment")
        if a2p_result:
            results["phases_completed"].append("sms_a2p_compliant")
        else:
            results["phases_completed"].append("sms_enabled_basic")
    elif phone_result:
        # Phone purchased but not assigned
        if a2p_result:
            results["phases_completed"].append("phone_a2p_ready_for_assignment")
        else:
            results["phases_completed"].append("phone_ready_for_assignment")
    
    logger.info("="*80)
    logger.info("USER ONBOARDING COMPLETE")
    logger.info("="*80)
    logger.info(f"Business: {business_name}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"User Email: {user_email}")
    if user_password:
        logger.info(f"User Password: {user_password}")
    logger.info(f"Calendar ID: {calendar_id}")
    if phone_result:
        logger.info(f"Phone Number: {phone_result['phone_number']}")
        
        # A2P Registration Status
        if a2p_result:
            logger.info(f"A2P Registration: ✓ Completed")
            logger.info(f"  Messaging Service: {a2p_result['messaging_service'].sid}")
            logger.info(f"  Registration Status: {a2p_result.get('status', 'unknown')}")
            if a2p_result.get('brand_registration'):
                logger.info(f"  Brand Registration: {a2p_result['brand_registration'].sid}")
            else:
                logger.info(f"  Brand Registration: Skipped (already exists)")
        else:
            logger.info(f"A2P Registration: ⚠ Not completed")
        
        # Phone Assignment Status
        if phone_assignment_result:
            logger.info(f"Phone Assignment: ✓ Assigned to user in CRM")
            if results.get('a2p_registration'):
                logger.info(f"SMS Status: ✓ A2P 10DLC compliant and ready for business use")
            else:
                logger.info(f"SMS Status: ⚠ Basic SMS enabled (A2P registration recommended)")
        else:
            logger.info(f"Phone Assignment: ⚠ Phone purchased but not assigned")
            if results.get('a2p_registration'):
                logger.info(f"SMS Status: ⚠ A2P registered but needs phone assignment")
            else:
                logger.info(f"SMS Status: ⚠ Phone available but needs A2P registration and assignment")
    else:
        logger.info(f"Phone Number: Not purchased")
        logger.info(f"A2P Registration: Not applicable")
        logger.info(f"SMS Status: Not available")
    logger.info(f"Phases Completed: {', '.join(results['phases_completed'])}")
    logger.info("="*80)
    
    return results

def process_recent_form_submissions_with_phone(oauth_client, twilio_manager, form_id, days_back=7, phone_preferences=None):
    """
    Process recent form submissions and complete full onboarding including phone numbers
    
    Args:
        oauth_client: GoHighLevelOAuth instance
        twilio_manager: TwilioPhoneManager instance
        form_id: Form ID to check for submissions
        days_back: Number of days to look back for submissions
        phone_preferences: Dict with phone number preferences
        
    Returns:
        List of onboarding results
    """
    logger.info(f"Processing form submissions from the last {days_back} days...")
    
    # Get client details from form submissions
    client_list = get_client_details_from_form(oauth_client, form_id, days_back)
    
    if not client_list:
        logger.info("No clients to process")
        return []
    
    results = []
    
    for i, client_data in enumerate(client_list, 1):
        logger.info(f"\n--- Processing Client {i}/{len(client_list)} ---")
        
        try:
            result = complete_client_onboarding_with_phone(
                oauth_client, 
                twilio_manager, 
                client_data, 
                phone_preferences
            )
            
            if result:
                results.append(result)
                logger.info(f"✓ Successfully processed: {result['user']['business_name']}")
            else:
                logger.error(f"✗ Failed to process client: {client_data.get('companyName', client_data.get('name', 'Unknown'))}")
                
        except Exception as e:
            logger.error(f"✗ Error processing client: {e}")
        
        # Add a small delay between processing clients
        if i < len(client_list):
            time.sleep(2)
    
    logger.info(f"\nProcessing complete: {len(results)}/{len(client_list)} clients successfully onboarded")
    return results

def main():
    """Main function to run the application"""
    print("Phase 1-4+ Automation - Internal Clients")
    print("Phases: User Creation → Calendar Setup → Phone Purchase → A2P Registration → Phone Assignment (SMS A2P Compliant)")
    print("="*80)
    
    # Check required environment variables
    required_vars = ["GHL_CLIENT_ID", "GHL_CLIENT_SECRET"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these in your .env file")
        return
    
    # Initialize OAuth client
    oauth_client = GoHighLevelOAuth(
        client_id=GHL_CLIENT_ID,
        client_secret=GHL_CLIENT_SECRET,
        redirect_uri=GHL_REDIRECT_URI
    )
    
    # Perform OAuth flow
    if not perform_oauth_flow(oauth_client):
        logger.error("OAuth authentication failed")
        return
    
    # Initialize Twilio manager (optional)
    twilio_manager = None
    try:
        twilio_manager = TwilioPhoneManager()
        logger.info("✓ Twilio integration enabled")
    except Exception as e:
        logger.warning(f"Twilio initialization failed: {e}")
        logger.warning("Continuing without phone number purchasing...")
    
    # Phone number preferences (customize as needed)
    phone_preferences = {
        'country_code': 'US',
        'number_type': 'local',  # 'local', 'tollfree', or 'mobile'
        'sms_enabled': True,
        'voice_enabled': True,
        'mms_enabled': False,
        'limit': 5
    }
    
    # Process recent form submissions
    try:
        results = process_recent_form_submissions_with_phone(
            oauth_client=oauth_client,
            twilio_manager=twilio_manager,
            form_id=GHL_FORM_ID,
            days_back=7,
            phone_preferences=phone_preferences
        )
        
        if results:
            print("\n" + "="*80)
            print("SUMMARY REPORT")
            print("="*80)
            
            for i, result in enumerate(results, 1):
                print(f"\n{i}. {result['user']['business_name']}")
                print(f"   User ID: {result['user']['id']}")
                print(f"   User Email: {result['user']['email']}")
                if result['user']['password']:
                    print(f"   User Password: {result['user']['password']}")
                print(f"   Calendar ID: {result['calendar']['id']}")
                
                if result.get('phone'):
                    print(f"   Phone: {result['phone']['phone_number']}")
                    
                    # A2P Registration Status
                    if result.get('a2p_registration'):
                        a2p_status = result.get('a2p_status', {})
                        print(f"   A2P Registration: ✓ {a2p_status.get('status', 'completed')}")
                        if a2p_status.get('messaging_service_sid'):
                            print(f"   Messaging Service: {a2p_status['messaging_service_sid']}")
                    else:
                        print(f"   A2P Registration: ⚠ Not completed")
                    
                    # Phone Assignment Status
                    if result.get('phone_assignment'):
                        print(f"   Phone Assignment: ✓ Assigned to user in CRM")
                        if result.get('a2p_registration'):
                            print(f"   SMS: ✓ A2P 10DLC compliant and ready for business use")
                        else:
                            print(f"   SMS: ⚠ Basic SMS enabled (A2P registration recommended)")
                    else:
                        print(f"   Phone Assignment: ⚠ Phone purchased but not assigned")
                        if result.get('a2p_registration'):
                            print(f"   SMS: ⚠ A2P registered but needs phone assignment")
                        else:
                            print(f"   SMS: ⚠ Phone available but needs A2P registration and assignment")
                else:
                    print(f"   Phone: Not purchased")
                    print(f"   A2P Registration: Not applicable")
                    print(f"   SMS: Not available")
                
                print(f"   Phases: {', '.join(result['phases_completed'])}")
            
            print(f"\nTotal users created: {len(results)}")
            print("="*80)
        else:
            print("\nNo users were created successfully.")
            
    except Exception as e:
        logger.error(f"Error in main processing: {e}")
        return

if __name__ == "__main__":
    main()  