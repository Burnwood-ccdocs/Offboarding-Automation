#!/usr/bin/env python3
"""
Automate login to https://crm.ccdocs.com/ with 2FA (TOTP), save cookies and headers.
"""

import os
import time
import json
import logging
import pyotp
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# Import area code module
from area_code import get_best_area_code, get_area_codes_batch_openai

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Credentials
email = os.getenv("CRM_EMAIL", "sarthaks@ccdocs.com")
password = os.getenv("CRM_PASSWORD", "CCDocs@2003")
totp_secret = os.getenv("CRM_TOTP_SECRET", "TETXRXJ4EMYCFTCWJSHFOPOPZ3V3MXX2")
crm_url = "https://crm.ccdocs.com/"

def uncheck_custom_checkboxes(driver):
    """Uncheck MMS and Toll Free checkboxes."""
    try:
        time.sleep(1)
        checkboxes = driver.find_elements(By.CSS_SELECTOR, ".n-checkbox-box-wrapper")
        logger.info(f"Found {len(checkboxes)} checkbox wrappers in filter dialog.")
        for i, wrapper in enumerate(checkboxes):
            try:
                label_elem = wrapper.find_element(By.XPATH, ".//following-sibling::span[contains(@class, 'n-checkbox__label')]")
                label_text = label_elem.text.strip()
                checkbox_box = wrapper.find_element(By.CSS_SELECTOR, ".n-checkbox-box")
                is_checked = bool(checkbox_box.find_elements(By.TAG_NAME, "svg"))
                logger.info(f"Checkbox {i}: label='{label_text}', checked={is_checked}")
                if label_text in ["MMS", "Toll Free"] and is_checked:
                    checkbox_box.click()
                    logger.info(f"Clicked to uncheck '{label_text}' checkbox.")
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error processing checkbox {i}: {e}")
        time.sleep(2)
    except Exception as e:
        logger.error(f"Could not process custom checkboxes: {e}")

def Phone_Number_Purchase(zip_codes=None, area_code=None):
    """
    Authenticate with CRM and purchase a phone number.
    
    Args:
        zip_codes (str or list): ZIP codes to use for area code lookup
        area_code (str): Specific area code to use (overrides zip_codes if provided)
        
    Returns:
        dict: Headers with cookies or None if failed
    """
    # Determine area code to use
    if area_code is None and zip_codes:
        logger.info(f"Looking up area codes for ZIP codes: {zip_codes}")
        
        # Parse ZIP codes to ensure they're in the right format
        from area_code import parse_zip_codes, get_area_codes_batch_openai
        parsed_zip_codes = parse_zip_codes(zip_codes)
        
        if parsed_zip_codes:
            # Get area codes directly using the OpenAI function
            area_codes_map = get_area_codes_batch_openai(parsed_zip_codes)
            
            # Since we've updated the function to return the same primary area code for all ZIP codes,
            # we can just take the area code from the first ZIP code
            if area_codes_map and len(area_codes_map) > 0:
                first_zip = list(area_codes_map.keys())[0]
                area_code = area_codes_map.get(first_zip, "")
                
                # Ensure area_code doesn't contain commas
                if area_code and ',' in area_code:
                    area_code = area_code.split(',')[0].strip()
                    logger.info(f"Extracted first area code from multi-area code: {area_code}")
            
                if area_code:
                    logger.info(f"Using primary area code {area_code} for all ZIP codes")
                else:
                    logger.warning(f"No area code found for ZIP codes")
            else:
                logger.warning(f"No area codes returned for ZIP codes: {zip_codes}")
        else:
            logger.warning(f"Could not parse any valid ZIP codes from: {zip_codes}")

    if area_code:
        logger.info(f"Will search for phone numbers with area code: {area_code}")
    else:
        logger.info("No area code specified, will search for any available numbers")

    logger.info(f"Authenticating to CRM as {email}")
    opts = Options()
    opts.headless = False  # Set to False to see the browser
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option("detach", True)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    
    try:
        logger.info(f"Opening CRM at {crm_url}")
        driver.get(crm_url)
        time.sleep(2)
        logger.info(f"Current URL: {driver.current_url}")

        # Find and fill email
        email_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='Your email address']"))
        )
        email_field.clear()
        email_field.send_keys(email)
        logger.info("Entered email.")

        # Find and fill password
        password_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='password']"))
        )
        password_field.clear()
        password_field.send_keys(password)
        logger.info("Entered password.")

        # Click Sign in
        try:
            sign_in_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))
            )
            sign_in_button.click()
            logger.info("Clicked Sign in using button[type='submit'].")
        except Exception as e:
            logger.warning(f"Could not click Sign in using button[type='submit']: {e}")
            # Try by button text
            try:
                sign_in_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Sign in') or contains(text(), 'Log in') or contains(text(), 'Login') or contains(text(), 'Continue') or contains(text(), 'Submit') or contains(text(), 'Next')]"))
                )
                sign_in_button.click()
                logger.info("Clicked Sign in using button text XPath.")
            except Exception as e2:
                logger.warning(f"Could not click Sign in using button text XPath: {e2}")
                # Try clicking the first visible button
                try:
                    buttons = driver.find_elements(By.TAG_NAME, "button")
                    for btn in buttons:
                        if btn.is_displayed() and btn.is_enabled():
                            btn.click()
                            logger.info("Clicked the first visible and enabled button as Sign in.")
                            break
                    else:
                        logger.error("No visible and enabled button found to click as Sign in.")
                except Exception as e3:
                    logger.error(f"Failed to click any button for Sign in: {e3}")
        time.sleep(3)

        # Handle OTP (2FA) if present
        if "authenticator" in driver.page_source.lower() or "security code" in driver.page_source.lower():
            logger.info("2FA/OTP page detected.")
            # Click 'Use Authenticator' radio button if present
            try:
                auth_radio = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//input[@type='radio' and (../label[contains(text(), 'Authenticator')] or following-sibling::span[contains(text(), 'Authenticator')]) ]"))
                )
                auth_radio.click()
                logger.info("Clicked 'Use Authenticator' radio button.")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"Could not click 'Use Authenticator' radio button: {e}")
            # Wait for OTP input boxes to appear (any input, not just type='text')
            try:
                # Wait for any input fields to appear in the OTP area
                otp_boxes = WebDriverWait(driver, 15).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".MuiInputBase-input, input"))
                )
                # Filter to only visible and enabled inputs
                otp_boxes = [box for box in otp_boxes if box.is_displayed() and box.is_enabled()]
                logger.info(f"Found {len(otp_boxes)} OTP input boxes (visible and enabled).")
                for i, box in enumerate(otp_boxes):
                    logger.info(f"OTP box {i}: type={box.get_attribute('type')}, class={box.get_attribute('class')}, name={box.get_attribute('name')}")
                # Only select the 6 OTP input boxes (type=number and class contains 'otp-input')
                otp_boxes = [box for box in otp_boxes if box.get_attribute('type') == 'number' and 'otp-input' in box.get_attribute('class')]
                logger.info(f"Filtered to {len(otp_boxes)} OTP input boxes (type=number, class contains 'otp-input').")
                totp = pyotp.TOTP(totp_secret)
                code = totp.now()
                logger.info(f"Generated OTP: {code}")
                for i, box in enumerate(otp_boxes[:6]):
                    box.clear()
                    box.send_keys(code[i])
                    time.sleep(0.1)
                logger.info("Entered OTP code into boxes.")
                if otp_boxes:
                    otp_boxes[min(5, len(otp_boxes)-1)].send_keys("\ue007")  # Enter key
                    logger.info("Pressed Enter in last OTP box.")
                time.sleep(2)
            except Exception as e:
                logger.error(f"Could not find or fill OTP input boxes: {e}")
        else:
            logger.info("No OTP page detected.")

        # Wait for dashboard/home
        time.sleep(5)
        logger.info(f"Final URL: {driver.current_url}")

        # Navigate to Settings with retries
        def click_settings_with_retry(max_retries=3):
            """Navigate to Settings with retry logic"""
            for attempt in range(max_retries):
                try:
                    logger.info(f"Attempting to click Settings (attempt {attempt + 1}/{max_retries})")
                    time.sleep(2)  # Wait between attempts
                    
                    # Try multiple approaches to find Settings
                    settings_selectors = [
                        "/html[1]/body[1]/div[1]/div[1]/div[4]/aside[1]/div[3]/div[1]/div[5]/nav[1]/a[1]/span[1]",
                        "//span[contains(text(), 'Settings')]",
                        "//a[contains(@href, 'settings')]",
                        "[data-testid*='settings']",
                        "[class*='settings']"
                    ]
                    
                    settings_elem = None
                    for selector in settings_selectors:
                        try:
                            if selector.startswith("//") or selector.startswith("/html"):
                                elements = driver.find_elements(By.XPATH, selector)
                            else:
                                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            
                            for elem in elements:
                                if elem.is_displayed() and elem.is_enabled():
                                    settings_elem = elem
                                    logger.info(f"Found Settings using selector: {selector}")
                                    break
                            if settings_elem:
                                break
                        except:
                            continue
                    
                    if settings_elem:
                        # Scroll to element and click
                        driver.execute_script("arguments[0].scrollIntoView(true);", settings_elem)
                        time.sleep(1)
                        settings_elem.click()
                        logger.info("✅ Clicked Settings successfully")
                        time.sleep(3)
                        return True
                    else:
                        logger.warning(f"Settings element not found on attempt {attempt + 1}")
                        
                except Exception as e:
                    logger.warning(f"Settings click attempt {attempt + 1} failed: {e}")
                    
                if attempt < max_retries - 1:
                    time.sleep(3)  # Wait before retry
            
            logger.error("❌ Failed to click Settings after all retries")
            return False

        # Navigate to Phone Numbers with retries
        def click_phone_numbers_with_retry(max_retries=3):
            """Navigate to Phone Numbers with retry logic"""
            for attempt in range(max_retries):
                try:
                    logger.info(f"Attempting to click Phone Numbers (attempt {attempt + 1}/{max_retries})")
                    time.sleep(2)
                    
                    # Try multiple approaches to find Phone Numbers
                    phone_selectors = [
                        "/html[1]/body[1]/div[1]/div[1]/div[4]/aside[1]/div[2]/div[1]/div[6]/nav[1]/a[12]/span[1]",
                        "//span[contains(text(), 'Phone Numbers')]",
                        "//a[contains(@href, 'phone')]",
                        "[data-testid*='phone']",
                        "[class*='phone']"
                    ]
                    
                    phone_elem = None
                    for selector in phone_selectors:
                        try:
                            if selector.startswith("//") or selector.startswith("/html"):
                                elements = driver.find_elements(By.XPATH, selector)
                            else:
                                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            
                            for elem in elements:
                                if elem.is_displayed() and elem.is_enabled():
                                    phone_elem = elem
                                    logger.info(f"Found Phone Numbers using selector: {selector}")
                                    break
                            if phone_elem:
                                break
                        except:
                            continue
                    
                    if phone_elem:
                        # Scroll to element and click
                        driver.execute_script("arguments[0].scrollIntoView(true);", phone_elem)
                        time.sleep(1)
                        phone_elem.click()
                        logger.info("✅ Clicked Phone Numbers successfully")
                        time.sleep(5)
                        return True
                    else:
                        logger.warning(f"Phone Numbers element not found on attempt {attempt + 1}")
                        
                except Exception as e:
                    logger.warning(f"Phone Numbers click attempt {attempt + 1} failed: {e}")
                    
                if attempt < max_retries - 1:
                    time.sleep(3)  # Wait before retry
            
            logger.error("❌ Failed to click Phone Numbers after all retries")
            return False

        # Execute navigation with retries
        settings_success = click_settings_with_retry()
        if settings_success:
            phone_numbers_success = click_phone_numbers_with_retry()
            
            if phone_numbers_success:
                # Click on the first button with absolute path (Add Number button)
                try:
                    add_number_button = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.XPATH, "/html[1]/body[1]/div[1]/div[1]/div[4]/section[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]/button[1]"))
                    )
                    add_number_button.click()
                    logger.info("Clicked on 'Add Number' button.")
                    time.sleep(3)
                    
                    # Click on the "Add Phone Number" option in the dropdown
                    try:
                        # Use the p element approach that works
                        p_elements = driver.find_elements(By.TAG_NAME, "p")
                        logger.info(f"Found {len(p_elements)} p elements on page")
                        
                        # Find and click the "Add Phone Number" p element
                        for p in p_elements:
                            if p.is_displayed() and "add phone number" in p.text.lower():
                                p.click()
                                logger.info(f"Clicked on p element with text: {p.text}")
                                time.sleep(3)
                                break
                        else:
                            logger.error("Could not find 'Add Phone Number' p element")
                        
                        # After successfully clicking "Add Phone Number", proceed with Filter button
                        time.sleep(5)  # Increase wait time to ensure page loads fully
                        
                        # Click on the Filter button - using the working approach
                        try:
                            # Find all buttons and look for "Filter" text (this approach works)
                            buttons = driver.find_elements(By.TAG_NAME, "button")
                            logger.info(f"Found {len(buttons)} buttons on page")
                            
                            # Find and click the Filter button
                            for btn in buttons:
                                if btn.is_displayed() and btn.text.strip() == "Filter":
                                    logger.info(f"Found Filter button by text: '{btn.text}'")
                                    btn.click()
                                    logger.info("Clicked on button with Filter text")
                                    time.sleep(3)
                                    break
                            else:
                                logger.error("Could not find Filter button")
                        except Exception as e:
                            logger.error(f"Could not click Filter button: {e}")

                        # Uncheck MMS and Toll Free checkboxes
                        uncheck_custom_checkboxes(driver)
                        
                        # Change dropdown from "Any part of number" to "First part of number"
                        try:
                            # Click on "Any part of number" to open dropdown
                            any_part_button = WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable((By.XPATH, "//div[contains(text(), 'Any part of number')]"))
                            )
                            driver.execute_script("arguments[0].scrollIntoView(true);", any_part_button)
                            time.sleep(1)
                            any_part_button.click()
                            logger.info("Clicked on 'Any part of number' button to open dropdown")
                            time.sleep(5)
                            
                            # Select "First part of number" from dropdown
                            first_part_option = WebDriverWait(driver, 15).until(
                                EC.element_to_be_clickable((By.XPATH, "//p[contains(text(), 'First part of number')]"))
                            )
                            first_part_option.click()
                            logger.info("Selected 'First part of number' from dropdown")
                            time.sleep(5)
                            
                            # Enter area code if provided
                            if area_code:
                                try:
                                    # Look for the input field
                                    area_code_input = WebDriverWait(driver, 15).until(
                                        EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Search By digit or phrases']"))
                                    )
                                    area_code_input.clear()
                                    time.sleep(1)
                                    area_code_input.send_keys(area_code)
                                    logger.info(f"Entered area code: {area_code} in the search field")
                                    time.sleep(2)
                                    
                                    # Click Apply button - Use JavaScript approach that works
                                    try:
                                        js_apply_script = """
                                        var buttons = document.querySelectorAll('button');
                                        for (var i = 0; i < buttons.length; i++) {
                                            var btn = buttons[i];
                                            if (btn.textContent.includes('Apply') && 
                                                btn.offsetParent !== null) {
                                                btn.click();
                                                return true;
                                            }
                                        }
                                        return false;
                                        """
                                        result = driver.execute_script(js_apply_script)
                                        if result:
                                            logger.info("Clicked Apply button using JavaScript")
                                            time.sleep(7)
                                        else:
                                            logger.error("Could not find Apply button with JavaScript")
                                    except Exception as e:
                                        logger.error(f"JavaScript Apply button click failed: {e}")
                                    
                                    # Take screenshot of the results
                                    driver.save_screenshot("crm_12_after_area_code_filter.png")
                                    
                                    # 📞 CAPTURE FIRST PHONE NUMBER DETAILS WITH STALE ELEMENT HANDLING
                                    phone_number = "Unknown"  # Initialize outside try block
                                    location = "Unknown"
                                    selected_number_info = {}
                                    first_row = None
                                    
                                    try:
                                        # Wait for phone numbers to load
                                        time.sleep(5)
                                        logger.info("🔍 Looking for fresh phone number elements...")
                                        
                                        def get_fresh_phone_data():
                                            """Get fresh phone data to avoid stale element issues"""
                                            # Focus only on the visible table that appears after filtering
                                            # This avoids looking at numbers behind overlays or in background tables
                                            logger.info("🔍 Looking for the visible phone number table...")
                                            
                                            try:
                                                # First try to find the most specific table that contains the phone numbers
                                                # This is usually the one that appears after filtering
                                                tables = driver.find_elements(By.CSS_SELECTOR, "table.table")
                                                if tables:
                                                    logger.info(f"Found {len(tables)} tables on the page")
                                                    # Use the last table as it's likely the most recently rendered one
                                                    visible_table = None
                                                    for table in reversed(tables):
                                                        if table.is_displayed():
                                                            visible_table = table
                                                            logger.info("Found visible table containing phone numbers")
                                                            break
                                                    
                                                    if visible_table:
                                                        # Get rows directly from the visible table
                                                        fresh_rows = visible_table.find_elements(By.CSS_SELECTOR, "tr")
                                                        logger.info(f"Found {len(fresh_rows)} rows in the visible table")
                                                    else:
                                                        # Fallback to all tr elements if no visible table found
                                                        fresh_rows = driver.find_elements(By.CSS_SELECTOR, "tr")
                                                        logger.info(f"No visible table found, using all {len(fresh_rows)} tr elements")
                                                else:
                                                    # Fallback to all tr elements
                                                    fresh_rows = driver.find_elements(By.CSS_SELECTOR, "tr")
                                                    logger.info(f"No tables found, using all {len(fresh_rows)} tr elements")
                                            except Exception as e:
                                                logger.warning(f"Error finding tables: {e}, falling back to direct tr search")
                                                # Last resort: get all tr elements
                                                fresh_rows = driver.find_elements(By.CSS_SELECTOR, "tr")
                                                logger.info(f"Found {len(fresh_rows)} total rows on page (fallback method)")
                                            
                                            # Filter for rows that are actually displayed and contain phone numbers
                                            phone_rows = []
                                            for row in fresh_rows:
                                                try:
                                                    if row.is_displayed():
                                                        row_text = row.text
                                                        # Check if this row contains a phone number and is not a header or existing number
                                                        if "+1" in row_text and any(char.isdigit() for char in row_text) and "Default Number" not in row_text:
                                                            # Prioritize rows with the target area code if specified
                                                            if area_code and f"+1 {area_code}" in row_text:
                                                                # Insert at beginning to prioritize area code matches
                                                                phone_rows.insert(0, row)
                                                                logger.info(f"📞 Found priority phone row with target area code: {row_text[:100]}...")
                                                            else:
                                                                phone_rows.append(row)
                                                                logger.info(f"📞 Found phone row: {row_text[:100]}...")
                                                except Exception as e:
                                                    # Skip rows that cause errors
                                                    continue
                                            
                                            return phone_rows
                                        
                                        phone_rows = get_fresh_phone_data()
                                        logger.info(f"Found {len(phone_rows)} rows with phone numbers")
                                        
                                        if phone_rows:
                                            first_row = phone_rows[0]
                                            
                                            # Extract phone number and details from the fresh row
                                            full_row_text = first_row.text.strip()
                                            logger.info(f"Full row text: '{full_row_text}'")
                                            
                                            # Extract phone number using regex
                                            phone_match = re.search(r'\+1\s*\d{3}-\d{3}-\d{4}', full_row_text)
                                            if phone_match:
                                                phone_number = phone_match.group().strip()
                                                logger.info(f"📞 Found phone number: {phone_number}")
                                                
                                                # Check if this might be an existing number
                                                if "Default Number" in full_row_text or "Current" in full_row_text:
                                                    logger.warning(f"⚠️ This appears to be an existing number: {phone_number}")
                                                    phone_number = "Existing"  # Mark as existing so we don't use it
                                                
                                                # Verify this is a new number with the correct area code
                                                if area_code:
                                                    # Extract just the area code from the found number
                                                    found_area_code = re.search(r'\+1\s*(\d{3})', phone_number)
                                                    if found_area_code:
                                                        found_area = found_area_code.group(1)
                                                        if found_area != area_code:
                                                            logger.warning(f"⚠️ Found number {phone_number} has area code {found_area}, but we want {area_code}")
                                                            phone_number = "Wrong Area"  # Mark as wrong area code
                                                        else:
                                                            logger.info(f"✅ Verified number {phone_number} has the correct area code {area_code}")
                                            
                                            # Extract location (look for city, state pattern)
                                            location_match = re.search(r'([A-Za-z\s]+,\s*[A-Z]{2})', full_row_text)
                                            if location_match:
                                                location = location_match.group().strip()
                                                logger.info(f"📍 Found location: {location}")
                                            
                                            # Try to extract additional details from cells
                                            try:
                                                cells = first_row.find_elements(By.TAG_NAME, "td")
                                                price = "Unknown"
                                                for i, cell in enumerate(cells):
                                                    cell_text = cell.text.strip()
                                                    if '$' in cell_text:
                                                        price = cell_text
                                                        logger.info(f"💰 Found price: {price} in cell {i}")
                                                        break
                                            except:
                                                price = "Unknown"
                                            
                                            # Create selected number info
                                            selected_number_info = {
                                                'phone_number': phone_number,
                                                'location': location,
                                                'price': price,
                                                'capabilities': "Unknown",
                                                'address_requirement': "Unknown",
                                                'type': "Unknown",
                                                'area_code': area_code,
                                                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")
                                            }
                                            
                                            # Skip if the phone number is invalid
                                            if phone_number in ["Existing", "Wrong Area", "Unknown"]:
                                                logger.warning(f"⚠️ Invalid phone number detected: {phone_number}")
                                                # We'll handle this later when trying to select the radio button
                                            
                                            logger.info(f"📞 CAPTURED PHONE NUMBER FOR PURCHASE:")
                                            logger.info(f"   Number: {phone_number}")
                                            logger.info(f"   Location: {location}")
                                            logger.info(f"   Price: {price}")
                                            logger.info(f"   Area Code: {area_code}")
                                            
                                            # Save selected number details to JSON file
                                            with open("selected_phone_number.json", "w") as f:
                                                json.dump(selected_number_info, f, indent=2)
                                            logger.info("💾 Saved selected phone number details to selected_phone_number.json")
                                    
                                    except Exception as e:
                                        logger.warning(f"Could not capture phone number details: {e}")
                                        selected_number_info = {
                                            "error": "Could not capture details",
                                            "area_code": area_code,
                                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                                        }
                                        
                                    # Select the radio button for the specific phone number row
                                    try:
                                        logger.info(f"🎯 Looking for radio button for phone number: {phone_number}")
                                        
                                        radio_clicked = False
                                        if phone_number != "Unknown":
                                            # Method 1: Find radio button in the first row directly
                                            try:
                                                if first_row:
                                                    logger.info("Attempting to click radio button in the first row...")
                                                    # Try to find the radio button in this row
                                                    radio_buttons = first_row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                                                    if radio_buttons:
                                                        radio_btn = radio_buttons[0]
                                                        # Scroll to the radio button to make sure it's in view
                                                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", radio_btn)
                                                        time.sleep(0.5)
                                                        
                                                        # Try direct click
                                                        try:
                                                            radio_btn.click()
                                                            logger.info(f"✅ SUCCESS: Clicked radio button for {phone_number}")
                                                            radio_clicked = True
                                                            time.sleep(1)
                                                        except Exception as e:
                                                            logger.warning(f"Direct click failed: {e}, trying JavaScript click")
                                                            # Try JavaScript click as fallback
                                                            driver.execute_script("arguments[0].click();", radio_btn)
                                                            logger.info(f"✅ SUCCESS: Clicked radio button using JavaScript for {phone_number}")
                                                            radio_clicked = True
                                                            time.sleep(1)
                                                    else:
                                                        logger.warning("No radio button found in the first row")
                                            except Exception as e:
                                                logger.warning(f"Method 1 failed: {e}")
                                            
                                            # Method 2: Find row containing the exact phone number
                                            if not radio_clicked:
                                                try:
                                                    logger.info("Trying Method 2: Find row with exact phone number...")
                                                    all_visible_rows = driver.find_elements(By.CSS_SELECTOR, "tr")
                                                    logger.info(f"Searching through {len(all_visible_rows)} rows for {phone_number}")
                                                    
                                                    for i, row in enumerate(all_visible_rows):
                                                        try:
                                                            if row.is_displayed():
                                                                row_text = row.text
                                                                logger.info(f"Row {i} text: {row_text[:100]}...")
                                                                
                                                                if phone_number in row_text:
                                                                    logger.info(f"🎯 Found matching row {i} containing {phone_number}")
                                                                    
                                                                    # Try to find and click radio button in this specific row
                                                                    radio_buttons = row.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                                                                    if radio_buttons:
                                                                        radio_btn = radio_buttons[0]
                                                                        # Scroll to element and try direct click
                                                                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", radio_btn)
                                                                        time.sleep(0.5)
                                                                        
                                                                        try:
                                                                            radio_btn.click()
                                                                            logger.info(f"✅ SUCCESS: Clicked radio button for {phone_number}")
                                                                            radio_clicked = True
                                                                            time.sleep(1)
                                                                            break
                                                                        except Exception as e:
                                                                            logger.warning(f"Direct click failed: {e}, trying JavaScript click")
                                                                            # Try JavaScript click
                                                                            driver.execute_script("arguments[0].click();", radio_btn)
                                                                            logger.info(f"✅ SUCCESS: Clicked radio button using JavaScript for {phone_number}")
                                                                            radio_clicked = True
                                                                            time.sleep(1)
                                                                            break
                                                                    else:
                                                                        logger.warning(f"No radio button found in row {i} with {phone_number}")
                                                        except Exception as e:
                                                            logger.warning(f"Error checking row {i}: {e}")
                                                            continue
                                                            
                                                except Exception as e:
                                                    logger.warning(f"Method 2 failed: {e}")
                                            
                                            # Method 3: JavaScript approach if previous methods fail
                                            if not radio_clicked:
                                                logger.info("🔄 Trying JavaScript approach to find and click radio button...")
                                                try:
                                                    # First try to click the radio button for the specific phone number
                                                    js_script = f"""
                                                    var rows = document.querySelectorAll('tr');
                                                    for (var i = 0; i < rows.length; i++) {{
                                                        var row = rows[i];
                                                        if (row.textContent.includes('{phone_number}')) {{
                                                            var radio = row.querySelector('input[type="radio"]');
                                                            if (radio && radio.offsetParent !== null) {{
                                                                radio.click();
                                                                return true;
                                                            }}
                                                        }}
                                                    }}
                                                    return false;
                                                    """
                                                    result = driver.execute_script(js_script)
                                                    if result:
                                                        logger.info(f"✅ SUCCESS: JavaScript clicked radio button for {phone_number}")
                                                        radio_clicked = True
                                                        time.sleep(1)
                                                    else:
                                                        # If that fails, try to click the first available radio button
                                                        js_script_first = """
                                                        var radios = document.querySelectorAll('input[type="radio"]');
                                                        for (var i = 0; i < radios.length; i++) {
                                                            if (radios[i].offsetParent !== null) {
                                                                radios[i].click();
                                                                return true;
                                                            }
                                                        }
                                                        return false;
                                                        """
                                                        result = driver.execute_script(js_script_first)
                                                        if result:
                                                            logger.info("✅ SUCCESS: JavaScript clicked first available radio button")
                                                            radio_clicked = True
                                                            time.sleep(1)
                                                        else:
                                                            logger.warning("JavaScript method could not find any radio button")
                                                except Exception as e:
                                                    logger.warning(f"JavaScript approach failed: {e}")
                                            
                                            # Method 4: Last resort - click first available radio button with warning
                                            if not radio_clicked:
                                                logger.warning("🚨 LAST RESORT: Trying to click any available radio button...")
                                                try:
                                                    all_radios = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                                                    logger.info(f"Found {len(all_radios)} total radio buttons")
                                                    
                                                    for i, radio in enumerate(all_radios):
                                                        try:
                                                            if radio.is_displayed() and radio.is_enabled():
                                                                # Scroll to the radio button
                                                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", radio)
                                                                time.sleep(0.5)
                                                                
                                                                try:
                                                                    radio.click()
                                                                    logger.warning(f"⚠️ CLICKED RADIO {i} - MAY NOT BE FOR {phone_number}")
                                                                    radio_clicked = True
                                                                    time.sleep(1)
                                                                    break
                                                                except:
                                                                    # Try JavaScript click
                                                                    driver.execute_script("arguments[0].click();", radio)
                                                                    logger.warning(f"⚠️ JS CLICKED RADIO {i} - MAY NOT BE FOR {phone_number}")
                                                                    radio_clicked = True
                                                                    time.sleep(1)
                                                                    break
                                                        except:
                                                            continue
                                                except Exception as e:
                                                    logger.error(f"Last resort method failed: {e}")
                                        
                                        if not radio_clicked:
                                            logger.error(f"❌ CRITICAL: Could not click radio button for {phone_number}")
                                            logger.error("🚨 PURCHASE MAY FAIL OR SELECT WRONG NUMBER!")
                                        
                                    except Exception as e:
                                        logger.error(f"Error selecting radio button: {e}")
                                    
                                    # Only proceed if radio button was clicked or force proceed
                                    proceed_anyway = True  # Set to False if you want to stop when radio fails
                                    if radio_clicked or proceed_anyway:
                                        # Click the "Proceed to Buy" button
                                        try:
                                            logger.info("🔍 Looking for 'Proceed to Buy' button...")
                                            
                                            # Take screenshot before looking for the button
                                            driver.save_screenshot("crm_before_proceed_button.png")
                                            logger.info("📸 Saved screenshot before looking for Proceed to Buy button")
                                            
                                            # Look specifically for the button at the bottom with shopping cart icon
                                            try:
                                                # First try by button text and shopping cart icon
                                                proceed_button = WebDriverWait(driver, 10).until(
                                                    EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Proceed to Buy') and .//i[contains(@class, 'cart') or contains(@class, 'shopping')]]"))
                                                )
                                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", proceed_button)
                                                time.sleep(1)
                                                proceed_button.click()
                                                logger.info("✅ Clicked 'Proceed to Buy' button with shopping cart icon")
                                                time.sleep(5)
                                            except Exception as e1:
                                                logger.warning(f"Could not find button with shopping cart icon: {e1}")
                                                
                                                # Try by exact text match at bottom of page
                                                try:
                                                    # Scroll to the bottom of the page first
                                                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                                                    time.sleep(1)
                                                    
                                                    proceed_button = WebDriverWait(driver, 10).until(
                                                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Proceed to Buy')]"))
                                                    )
                                                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", proceed_button)
                                                    time.sleep(1)
                                                    proceed_button.click()
                                                    logger.info("✅ Clicked 'Proceed to Buy' button by text")
                                                    time.sleep(5)
                                                except Exception as e2:
                                                    logger.warning(f"Could not find button by text: {e2}")
                                                    
                                                    # Try by class and partial text
                                                    try:
                                                        buttons = driver.find_elements(By.CSS_SELECTOR, ".btn, .button, button")
                                                        logger.info(f"Found {len(buttons)} buttons on the page")
                                                        
                                                        for i, btn in enumerate(buttons):
                                                            try:
                                                                btn_text = btn.text.strip()
                                                                logger.info(f"Button {i}: '{btn_text}'")
                                                                
                                                                if "proceed" in btn_text.lower() and "buy" in btn_text.lower():
                                                                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                                                                    time.sleep(1)
                                                                    btn.click()
                                                                    logger.info(f"✅ Clicked button with text: '{btn_text}'")
                                                                    time.sleep(5)
                                                                    break
                                                            except Exception as e:
                                                                continue
                                                        else:
                                                            # If no button found, try JavaScript approach
                                                            logger.info("Trying JavaScript approach for Proceed to Buy button...")
                                                            js_script = """
                                                            var buttons = document.querySelectorAll('button');
                                                            for (var i = 0; i < buttons.length; i++) {
                                                                var text = buttons[i].textContent.toLowerCase();
                                                                if (text.includes('proceed') && text.includes('buy')) {
                                                                    buttons[i].click();
                                                                    return true;
                                                                }
                                                            }
                                                            return false;
                                                            """
                                                            result = driver.execute_script(js_script)
                                                            if result:
                                                                logger.info("✅ Clicked Proceed to Buy button using JavaScript")
                                                                time.sleep(5)
                                                            else:
                                                                logger.error("❌ Could not find Proceed to Buy button")
                                                    except Exception as e3:
                                                        logger.warning(f"Error finding buttons: {e3}")
                                            
                                            # Take screenshot after proceeding to buy
                                            driver.save_screenshot("crm_after_proceed_to_buy.png")
                                            logger.info("📸 Saved screenshot after clicking Proceed to Buy")
                                            
                                            # Wait for the purchase to complete
                                            logger.info("Waiting for purchase to complete...")
                                            time.sleep(10)
                                            
                                            # Take final screenshot
                                            driver.save_screenshot("crm_purchase_complete.png")
                                            logger.info("📸 Saved final purchase screenshot")
                                            
                                        except Exception as e:
                                            logger.error(f"Error clicking Proceed button: {e}")
                                            driver.save_screenshot("crm_proceed_button_error.png")
                                            logger.info("📸 Saved error screenshot")
                                    else:
                                        logger.error("🚨 STOPPED: Radio button not clicked and proceed_anyway=False")
                                        logger.error("🛑 Phone number purchase ABORTED to prevent wrong selection!")
                                    
                                except Exception as e:
                                    logger.error(f"Could not enter area code: {e}")
                        except Exception as e:
                            logger.error(f"Could not change dropdown to 'First part of number': {e}")
                        
                    except Exception as e:
                        logger.error(f"Could not click on 'Add Phone Number' option: {e}")
                except Exception as e:
                    logger.error(f"Could not click on 'Add Number' button: {e}")
                else:
                    logger.error("❌ Failed to navigate to Phone Numbers section")
            else:
                logger.error("❌ Failed to navigate to Settings section")

            # Save cookies
            cookies = driver.get_cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            with open("crm_cookies.json", "w") as f:
                json.dump(cookies, f)
            logger.info("Saved cookies to crm_cookies.json")

            # Save headers
            headers = {
                "Cookie": cookie_str,
                "User-Agent": driver.execute_script("return navigator.userAgent;"),
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": crm_url
            }
            with open("crm_headers.json", "w") as f:
                json.dump(headers, f)
            logger.info("Saved headers to crm_headers.json")
            
            # Return headers along with selected phone number info if available
            result = {"headers": headers}

            # ✅ FIX: Use current session data, not old JSON file
            if 'selected_number_info' in locals() and selected_number_info.get('phone_number') != 'Unknown':
                result["selected_phone_number"] = selected_number_info
                logger.info(f"🎯 PHONE NUMBER PURCHASE COMPLETED: {selected_number_info['phone_number']}")
            else:
                # Try to read JSON only if no current session data
                try:
                    with open("selected_phone_number.json", "r") as f:
                        phone_info = json.load(f)
                        # Only use if it doesn't have error and has current timestamp (within last 10 minutes)
                        if (phone_info.get('error') != "Could not capture details" and 
                            phone_info.get('phone_number') != 'Unknown'):
                            result["selected_phone_number"] = phone_info
                            logger.info(f"🎯 PHONE NUMBER PURCHASE DATA: {phone_info.get('phone_number', 'Unknown')}")
                        else:
                            result["selected_phone_number"] = None
                            logger.warning("⚠️ Phone number purchase attempted but no valid data captured")
                except:
                    result["selected_phone_number"] = None
                    logger.warning("⚠️ No phone number purchase data available")
            
            return result
    except Exception as e:
        logger.error(f"Error during CRM authentication: {str(e)}")
        return None
    finally:
        logger.info("Authentication completed. Browser will remain open for inspection.")
        # driver.quit()  # Uncomment to close browser automatically

def parse_zip_codes(zip_codes_str):
    """
    Parse ZIP codes from a string, handling various formats.
    
    Args:
        zip_codes_str (str): String containing ZIP codes
        
    Returns:
        list: List of ZIP codes
    """
    if not zip_codes_str:
        return []
        
    # Handle comma-separated list
    if ',' in zip_codes_str:
        return [z.strip() for z in zip_codes_str.split(',') if z.strip()]
        
    # Handle space-separated list
    if ' ' in zip_codes_str:
        return [z.strip() for z in zip_codes_str.split() if z.strip()]
        
    # Extract all 5-digit numbers from the string
    zip_matches = re.findall(r'\b\d{5}\b', zip_codes_str)
    if zip_matches:
        return zip_matches
        
    # If it's just a single ZIP code
    if zip_codes_str.strip().isdigit() and len(zip_codes_str.strip()) == 5:
        return [zip_codes_str.strip()]
        
    return []

def capture_all_phone_numbers(driver):
    """
    Capture all available phone numbers from the table with their complete details.
    
    Args:
        driver: Selenium WebDriver instance
        
    Returns:
        list: List of dictionaries containing phone number details
    """
    try:
        logger.info("📋 CAPTURING ALL AVAILABLE PHONE NUMBERS FROM TABLE...")
        
        # Wait for the table to load
        time.sleep(3)
        
        # Find all table rows with phone number data
        phone_rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
        logger.info(f"Found {len(phone_rows)} phone number rows in table")
        
        all_phone_numbers = []
        
        for i, row in enumerate(phone_rows):
            try:
                phone_data = {}
                
                # Extract phone number
                try:
                    phone_cell = row.find_element(By.CSS_SELECTOR, "td[data-col-key='phoneNumber']")
                    phone_number = phone_cell.text.strip().split('\n')[0]  # Get first line if multiple lines
                    phone_data['phone_number'] = phone_number
                    
                    # Try to extract location/city from the same cell
                    try:
                        location_elements = phone_cell.find_elements(By.TAG_NAME, "span")
                        location = ""
                        for elem in location_elements:
                            text = elem.text.strip()
                            if text and text != phone_number and not text.startswith('+'):
                                location = text
                                break
                        phone_data['location'] = location if location else "Unknown"
                    except:
                        phone_data['location'] = "Unknown"
                        
                except Exception as e:
                    logger.warning(f"Could not extract phone number from row {i}: {e}")
                    continue
                
                # Extract capabilities
                try:
                    capabilities_cell = row.find_element(By.CSS_SELECTOR, "td[data-col-key='capabilities']")
                    capabilities = capabilities_cell.text.strip()
                    phone_data['capabilities'] = capabilities
                except:
                    phone_data['capabilities'] = "Unknown"
                
                # Extract address requirement
                try:
                    address_cell = row.find_element(By.CSS_SELECTOR, "td[data-col-key='addressRequirement']")
                    address_requirement = address_cell.text.strip()
                    phone_data['address_requirement'] = address_requirement
                except:
                    phone_data['address_requirement'] = "Unknown"
                
                # Extract price
                try:
                    price_cell = row.find_element(By.CSS_SELECTOR, "td[data-col-key='price']")
                    price = price_cell.text.strip()
                    phone_data['price'] = price
                except:
                    phone_data['price'] = "Unknown"
                
                # Extract type if available
                try:
                    type_cell = row.find_element(By.CSS_SELECTOR, "td[data-col-key='type']")
                    number_type = type_cell.text.strip()
                    phone_data['type'] = number_type
                except:
                    phone_data['type'] = "Unknown"
                
                # Check if radio button exists for selection
                try:
                    radio_button = row.find_element(By.CSS_SELECTOR, "input[type='radio']")
                    phone_data['selectable'] = True
                    phone_data['radio_index'] = i
                except:
                    phone_data['selectable'] = False
                    phone_data['radio_index'] = None
                
                # Add metadata
                phone_data['row_index'] = i
                phone_data['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S")
                
                all_phone_numbers.append(phone_data)
                
                logger.info(f"📞 Row {i+1}: {phone_data['phone_number']} | {phone_data['location']} | {phone_data['price']} | {phone_data['capabilities']}")
                
            except Exception as e:
                logger.warning(f"Error processing row {i}: {e}")
                continue
        
        # Save all phone numbers to JSON file
        with open("all_available_phone_numbers.json", "w") as f:
            json.dump(all_phone_numbers, f, indent=2)
        
        logger.info(f"💾 SAVED {len(all_phone_numbers)} PHONE NUMBERS TO all_available_phone_numbers.json")
        
        # Print summary
        logger.info("📈 PHONE NUMBER SUMMARY:")
        for phone in all_phone_numbers[:5]:  # Show first 5
            logger.info(f"   {phone['phone_number']} - {phone['location']} - {phone['price']}")
        
        if len(all_phone_numbers) > 5:
            logger.info(f"   ... and {len(all_phone_numbers) - 5} more numbers")
        
        return all_phone_numbers
        
    except Exception as e:
        logger.error(f"Error capturing phone numbers: {e}")
        return []

def select_phone_number_by_criteria(driver, all_numbers, criteria=None):
    """
    Select a phone number based on specific criteria.
    
    Args:
        driver: Selenium WebDriver instance
        all_numbers: List of phone number dictionaries
        criteria: Dictionary with selection criteria (e.g., {'location': 'Dallas', 'price': 'lowest'})
        
    Returns:
        dict: Selected phone number details or None
    """
    try:
        if not all_numbers:
            logger.error("No phone numbers available for selection")
            return None
        
        selectable_numbers = [num for num in all_numbers if num.get('selectable', False)]
        
        if not selectable_numbers:
            logger.error("No selectable phone numbers found")
            return None
        
        selected_number = None
        
        if criteria:
            logger.info(f"Applying selection criteria: {criteria}")
            
            # Filter by location if specified
            if 'location' in criteria:
                location_filter = criteria['location'].lower()
                filtered = [num for num in selectable_numbers if location_filter in num.get('location', '').lower()]
                if filtered:
                    selectable_numbers = filtered
                    logger.info(f"Filtered to {len(selectable_numbers)} numbers matching location '{criteria['location']}'")
            
            # Filter by price if specified
            if 'price' in criteria and criteria['price'] == 'lowest':
                try:
                    # Convert prices to float for comparison (assuming format like "$1.00")
                    for num in selectable_numbers:
                        price_str = num.get('price', '0')
                        price_value = float(re.sub(r'[^\d.]', '', price_str)) if price_str != 'Unknown' else 999.99
                        num['price_value'] = price_value
                    
                    selected_number = min(selectable_numbers, key=lambda x: x.get('price_value', 999.99))
                    logger.info(f"Selected lowest price number: {selected_number['phone_number']} at {selected_number['price']}")
                except Exception as e:
                    logger.warning(f"Could not sort by price: {e}")
                    selected_number = selectable_numbers[0]
            
            # Filter by capabilities if specified
            if 'capabilities' in criteria:
                required_capability = criteria['capabilities'].lower()
                filtered = [num for num in selectable_numbers if required_capability in num.get('capabilities', '').lower()]
                if filtered:
                    selectable_numbers = filtered
                    logger.info(f"Filtered to {len(selectable_numbers)} numbers with capability '{criteria['capabilities']}'")
        
        # If no specific selection made, use first available
        if not selected_number:
            selected_number = selectable_numbers[0]
            logger.info(f"Selected first available number: {selected_number['phone_number']}")
        
        # Click the radio button to select this number
        try:
            radio_buttons = driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
            if selected_number['radio_index'] < len(radio_buttons):
                radio_buttons[selected_number['radio_index']].click()
                logger.info(f"✅ Selected phone number: {selected_number['phone_number']}")
                time.sleep(1)
                
                # Save selected number details
                with open("selected_phone_number.json", "w") as f:
                    json.dump(selected_number, f, indent=2)
                logger.info("💾 Saved selected phone number details")
                
                return selected_number
            else:
                logger.error(f"Radio button index {selected_number['radio_index']} out of range")
                return None
                
        except Exception as e:
            logger.error(f"Could not click radio button for selected number: {e}")
            return None
            
    except Exception as e:
        logger.error(f"Error in phone number selection: {e}")
        return None

if __name__ == "__main__":
    # Example usage
    test_zip_codes = "75034, 75024"
    # Parse ZIP codes from string
    zip_list = parse_zip_codes(test_zip_codes)
    if zip_list:
        logger.info(f"Parsed ZIP codes: {zip_list}")
        # Call the phone number purchase function with ZIP codes
        headers = Phone_Number_Purchase(zip_codes=zip_list)
    else:
        # Call without ZIP codes
        headers = Phone_Number_Purchase()
        
    if headers:
        logger.info("CRM authentication successful, number purchase successfully!")
    else:
        logger.error("CRM authentication failed!")