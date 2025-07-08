import os
import openai
import logging
import json
import time
import dotenv
import re

dotenv.load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")

# Simple cache to avoid duplicate API calls in the same session
_area_code_cache = {}

def get_area_codes_for_zip_openai(zip_code):
    """
    Get primary area code for a ZIP code using OpenAI with the new prompt format.
    
    Args:
        zip_code (str): The ZIP code to look up
        
    Returns:
        list: List containing only the primary area code or empty list if none found
    """
    if not openai.api_key:
        logger.warning("OpenAI API key not found. Set OPENAI_API_KEY environment variable.")
        return []
    
    try:
        # Make API call to OpenAI using the new prompt format
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides accurate area code information for US ZIP codes. Return only the primary area code, no overlays."},
                {"role": "user", "content": f"Give me area code info for these ZIP codes:\n[{zip_code}]\n\nFormat the response like this (grouped by overlay complex):\n### Area Code: [code]\n**Overlays:** [overlay(s) or ❌ None]\n**ZIPs:** [list of ZIP codes]\n\nRules:\nGroup ZIPs under a single entry if they share the same overlay complex\nDo not repeat the same overlay complex in multiple entries\nNo extra explanations, just compact and clean output\n\nreturn only the primary area code no overlays."}
            ],
            temperature=0
        )
        
        # Parse the response to extract only the primary area code
        content = response.choices[0].message.content
        logger.info(f"OpenAI response for ZIP {zip_code}: {content}")
        
        # Extract area code from the formatted response
        area_code_match = re.search(r'### Area Code: (\d{3})', content)
        if area_code_match:
            primary_area_code = area_code_match.group(1)
            logger.info(f"OpenAI found primary area code for ZIP {zip_code}: {primary_area_code}")
            return [primary_area_code]
        else:
            logger.warning(f"Could not extract area code from OpenAI response for ZIP {zip_code}")
            return []
            
    except Exception as e:
        logger.error(f"Error getting area codes from OpenAI for ZIP {zip_code}: {str(e)}")
        return []

def get_area_codes_for_zip(zip_code):
    """
    Get area codes for a single ZIP code.
    Tries cache first, then OpenAI, falls back to uszipcode library.
    
    Args:
        zip_code (str): The ZIP code to look up
        
    Returns:
        list: List of area codes for the ZIP code or empty list if none found
    """
    # Check cache first
    if zip_code in _area_code_cache:
        logger.info(f"Using cached area codes for ZIP {zip_code}: {_area_code_cache[zip_code]}")
        return _area_code_cache[zip_code]
    
    # Try OpenAI first
    openai_codes = get_area_codes_for_zip_openai(zip_code)
    if openai_codes:
        _area_code_cache[zip_code] = openai_codes
        return openai_codes
    
    # No offline fallback since uszipcode is no longer used; returning empty list.
    logger.info("OpenAI did not return area code; offline lookup disabled.")
    _area_code_cache[zip_code] = []
    return []

def get_common_area_codes(zip_codes):
    """
    Find common area codes across multiple ZIP codes.
    Uses batch lookup to minimize API calls.
    
    Args:
        zip_codes (list): List of ZIP codes to check
        
    Returns:
        tuple: (all_area_codes, common_area_codes)
            - all_area_codes: Dictionary mapping ZIP codes to their area codes
            - common_area_codes: List of area codes common to all ZIP codes
    """
    if not zip_codes:
        return {}, []
    
    # Clean up ZIP codes
    clean_zips = [z.strip() for z in zip_codes if z.strip()]
    if not clean_zips:
        return {}, []
    
    # Try batch lookup first to minimize API calls
    all_area_codes = {}
    if len(clean_zips) > 1:
        batch_results = get_area_codes_batch_openai(clean_zips)
        if batch_results:
            all_area_codes = batch_results
            logger.info(f"Used batch lookup for {len(clean_zips)} ZIP codes")
    
    # Fill in any missing ZIP codes with individual calls
    for z in clean_zips:
        if z not in all_area_codes:
            area_codes = get_area_codes_for_zip(z)
            if area_codes:
                all_area_codes[z] = area_codes
    
    # Find common area codes
    if all_area_codes:
        area_code_sets = [set(codes) for codes in all_area_codes.values()]
        common_codes = sorted(set.intersection(*area_code_sets)) if area_code_sets else []
        return all_area_codes, common_codes
    else:
        return {}, []

def get_best_area_code(zip_codes):
    """
    Get the best area code to use for a list of ZIP codes.
    If there are common area codes, returns the first one.
    Otherwise returns the first area code of the first ZIP code.
    
    Args:
        zip_codes (str or list): Single ZIP code string, comma-separated ZIP codes, or list of ZIP codes
        
    Returns:
        tuple: (area_code, all_area_codes, common_area_codes)
            - area_code: The recommended area code to use (str or None)
            - all_area_codes: Dictionary mapping ZIP codes to their area codes
            - common_area_codes: List of area codes common to all ZIP codes
    """
    # Handle different input types
    if isinstance(zip_codes, str):
        if ',' in zip_codes:
            zip_list = [z.strip() for z in zip_codes.split(',')]
        else:
            zip_list = [zip_codes.strip()]
    else:
        zip_list = zip_codes
    
    # Filter out empty strings
    zip_list = [z for z in zip_list if z]
    
    if not zip_list:
        return None, {}, []
    
    all_area_codes, common_codes = get_common_area_codes(zip_list)
    
    # Determine best area code
    if common_codes:
        # If there are common area codes, use the first one
        return common_codes[0], all_area_codes, common_codes
    elif all_area_codes:
        # Otherwise use the first area code of the first ZIP code
        first_zip = next(iter(all_area_codes))
        if all_area_codes[first_zip]:
            return all_area_codes[first_zip][0], all_area_codes, common_codes
    
    return None, all_area_codes, common_codes

def get_area_codes_batch_openai(zip_codes):
    """
    Get primary area codes for multiple ZIP codes in a single OpenAI call using the new prompt format.
    Uses cache to avoid duplicate calls.
    
    Args:
        zip_codes (list): List of ZIP codes to look up
        
    Returns:
        dict: Dictionary mapping ZIP codes to their primary area codes
    """
    if not openai.api_key or not zip_codes:
        return {}
    
    # Check cache for already known ZIP codes
    uncached_zips = []
    cached_results = {}
    
    for zip_code in zip_codes:
        if zip_code in _area_code_cache:
            cached_results[zip_code] = _area_code_cache[zip_code]
        else:
            uncached_zips.append(zip_code)
    
    if cached_results:
        logger.info(f"Using cached results for {len(cached_results)} ZIP codes")
    
    if not uncached_zips:
        return cached_results
    
    try:
        # Make API call to OpenAI using the new prompt format for uncached ZIP codes only
        zip_list_str = ', '.join(uncached_zips)
        response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides accurate area code information for US ZIP codes. Return only the primary area code for each ZIP, no overlays."},
                {"role": "user", "content": f"""Give me area code info for these ZIP codes:
                    [{zip_list_str}]

                    Format the response like this (grouped by overlay complex):
                    ### Area Code: [primary code]  
                    **Overlays:** [overlay(s) or ❌ None]  
                    **ZIPs:** [list of ZIP codes]

                    Rules:
                    - Always return only one entry per overlay complex, using the **primary area code** as the header (e.g., 972 over 469 or 214)
                    - Group ZIPs under a single entry if they share the same overlay complex
                    - Do not repeat the same overlay complex in multiple entries
                    - Show overlays, but do not list overlays as the primary area code
                    - No extra explanations, just compact and clean output
                    """}
            ],
            temperature=0
        )
        
        # Parse the response to extract primary area codes
        content = response.choices[0].message.content
        logger.info(f"OpenAI batch response: {content}")
        
        # Extract area codes and their associated ZIP codes from the formatted response
        result = {}
        
        # Find all area code sections
        sections = re.findall(r'### Area Code: (\d{3})\s*\*\*Overlays:\*\*.*?\*\*ZIPs:\*\* ([^\n]+)', content, re.DOTALL)
        
        for area_code, zips_str in sections:
            # Extract ZIP codes from the string (handle various formats)
            zip_matches = re.findall(r'\b\d{5}\b', zips_str)
            for zip_code in zip_matches:
                if zip_code in uncached_zips:  # Only include requested uncached ZIP codes
                    result[zip_code] = [area_code]
                    _area_code_cache[zip_code] = [area_code]  # Cache the result
        
        # If parsing failed, try a simpler approach
        if not result:
            # Look for any area codes mentioned and map to ZIP codes
            area_code_matches = re.findall(r'\b(\d{3})\b', content)
            if area_code_matches and len(area_code_matches) >= len(uncached_zips):
                for i, zip_code in enumerate(uncached_zips):
                    if i < len(area_code_matches):
                        result[zip_code] = [area_code_matches[i]]
                        _area_code_cache[zip_code] = [area_code_matches[i]]  # Cache the result
        
        logger.info(f"OpenAI batch lookup results: {result}")
        
        # Combine cached and new results
        final_result = {**cached_results, **result}
        return final_result
            
    except Exception as e:
        logger.error(f"Error getting batch area codes from OpenAI: {str(e)}")
        return {}

def parse_zip_codes(zip_codes_input):
    """
    Parse ZIP codes from various input formats
    
    Args:
        zip_codes_input: String or List containing ZIP codes in various formats
        
    Returns:
        List of ZIP code strings
    """
    if not zip_codes_input:
        return []
    
    # If input is already a list, process it directly
    if isinstance(zip_codes_input, list):
        return [str(zip_code).strip() for zip_code in zip_codes_input if zip_code]
    
    # Handle various string formats
    # 1. Comma-separated list: "12345, 67890"
    # 2. JSON array: "[\"12345\", \"67890\"]"
    # 3. Space-separated list: "12345 67890"
    # 4. Newline-separated list: "12345\n67890"
    
    # Try to parse as JSON first
    try:
        parsed = json.loads(zip_codes_input)
        if isinstance(parsed, list):
            return [str(zip_code).strip() for zip_code in parsed if zip_code]
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Try other formats
    # Replace common separators with commas
    normalized = re.sub(r'[\s\n\t;|]+', ',', str(zip_codes_input))
    
    # Split by comma and clean up
    zip_codes = []
    for item in normalized.split(','):
        # Extract 5-digit ZIP codes
        matches = re.findall(r'\b\d{5}\b', item)
        zip_codes.extend(matches)
    
    return list(set(zip_codes))  # Remove duplicates

if __name__ == "__main__":
    # Example usage when run as a script
    test_zip_codes = ["75034", "75024"]
    
    # Test batch lookup with OpenAI
    batch_results = get_area_codes_batch_openai(test_zip_codes)
    if batch_results:
        print("\nOpenAI Batch Results:")
        for zip_code, codes in batch_results.items():
            print(f"  {zip_code}: {codes}")
    
    # Test individual ZIP code lookup
    for z in test_zip_codes:
        area_codes = get_area_codes_for_zip(z)
        print(f"{z}: {area_codes}")
    
    # Test finding common area codes
    all_codes, common_codes = get_common_area_codes(test_zip_codes)
    print("\nAll area codes by ZIP:")
    for zip_code, codes in all_codes.items():
        print(f"  {zip_code}: {codes}")
        
    print(f"\n✅ Common Area Code(s): {common_codes}")
    
    # Test getting best area code
    best_code, _, _ = get_best_area_code(test_zip_codes)
    print(f"\n✅ Best Area Code to use: {best_code}")