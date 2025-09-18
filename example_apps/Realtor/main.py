import hyphae
import requests
from typing import List, Dict, Optional
import re
import json
import traceback
import subprocess
from hyphae.tools.respond_to_user import RespondToUserReturnType


class RealtorApp:
    def __init__(self):
        self.search_results = []
        self.parsed_request = {}
        

    @hyphae.tool("Send a message back to the user with property search results", icon="message")
    @hyphae.args(
        response="The message to send back to the user"
    )
    def RespondToUser(self, response: str) -> RespondToUserReturnType:
        r = RespondToUserReturnType()
        r.response = response
        return r

    @hyphae.tool("This tool executes a shell command and returns the output. The system is Alpine on arm64, python packages available through apk or pip. Whenever given a file thats attached, cat that file to output the content of the file, dont get stuck ", icon="apple.terminal")
    @hyphae.args(command="The shell command to execute", timeout="The timeout (seconds) for the command execution")
    def ExecuteCommand(self, command: str, timeout: int) -> str:
        print("ExecuteCommand: ", command)
        return self._run_cmd(command, timeout)

    def _run_cmd(self, command : str, timeout : int) -> str: #demo calling other funcs from within a tool, and that non decorated funcs dont become tools
        output = ""
        try:
            output = subprocess.check_output(
                command, stderr=subprocess.STDOUT, shell=True, timeout=timeout,
                universal_newlines=True)
        except subprocess.CalledProcessError as exc:
            return f"Shell Command Returned Error Code:`{str(exc.returncode)}`\n```\n" + exc.output + "\n```"
        except subprocess.TimeoutExpired:
            return  "Shell Command timed after {timeout} seconds"
        except Exception as e:
            return f"Shell Command Error: ```\n{str(e)}\n```\n Traceback:\n```\n{traceback.format_exc()}\n```"
        else:
            return f"```\n$ {command}\n {output}\n```"
            
    @hyphae.tool("Scout for properties based on type, location, and budget. Expect .md,.pdf and .txt files as inout a well, in that case use the built in EXECUTE COMMAND tool to cat the file and get the content.", icon="house.fill")
    @hyphae.args(
        location="City, state or zip code to search in (e.g., 'Austin, TX' or '90210')",
        property_type="Type of property: 'house', 'condo', 'townhouse', 'apartment', 'multi-family', 'any'",
        max_price="Maximum price budget (e.g., 500000 for $500k)",
        min_price="Minimum price (optional, default 0)",
        bedrooms="Minimum number of bedrooms (optional)",
        bathrooms="Minimum number of bathrooms (optional)"
    )

    def Scout(self, location: str = "", property_type: str = "any", max_price: int = 1000000, 
              min_price: int = 0, bedrooms: int = 0, bathrooms: int = 0) -> str:
        """Scout for properties using Zillow API via RapidAPI. Use parsed parameters from User_Request tool if available."""
        
        # Use parsed parameters if available and arguments not explicitly provided
        if self.parsed_request:
            location = location or self.parsed_request.get("location", "")
            property_type = property_type if property_type != "any" else self.parsed_request.get("property_type", "any")
            max_price = max_price if max_price != 1000000 else self.parsed_request.get("max_price", 1000000)
            min_price = min_price if min_price != 0 else self.parsed_request.get("min_price", 0)
            bedrooms = bedrooms if bedrooms != 0 else self.parsed_request.get("bedrooms", 0)
            bathrooms = bathrooms if bathrooms != 0 else self.parsed_request.get("bathrooms", 0)
        
        # Validate that we have a location
        if not location:
            return "❌ **Error:** Location is required. Please specify a city, state, or zip code to search."
        
        print("Scouting properties on Zillow...")
        
        try:
            # RapidAPI Zillow endpoint
            url = "https://zillow-com1.p.rapidapi.com/propertyExtendedSearch"
            
            # Map our property types to Zillow's expected values
            home_type_mapping = {
                "house": "Houses",
                "condo": "Condos", 
                "townhouse": "Townhomes",
                "apartment": "Apartments",
                "multi-family": "Multi-family",
                "any": "Houses,Condos,Townhomes,Apartments,Multi-family"
            }
            
            home_types = home_type_mapping.get(property_type.lower(), "Houses,Condos,Townhomes,Apartments,Multi-family")
            
            # Setup request parameters
            querystring = {
                "location": location,
                "status_type": "ForSale",
                "home_type": home_types,
                "sort": "Homes_for_You",
                "page": "1"
            }
            
            # Add price filters if specified - using correct API parameter names
            if min_price > 0:
                querystring["minPrice"] = str(min_price)
            if max_price < 10000000:  # Only add if it's a reasonable max
                querystring["maxPrice"] = str(max_price)
            
            # Add bedroom/bathroom filters if specified - using correct API parameter names  
            if bedrooms > 0:
                querystring["bedsMin"] = str(bedrooms)
            if bathrooms > 0:
                querystring["bathsMin"] = str(bathrooms)
            
            # Headers for RapidAPI
            headers = {
                "X-RapidAPI-Key": "ADD_YOUR_RAPIDAPI_KEY_HERE",  
                "X-RapidAPI-Host": "zillow-com1.p.rapidapi.com"
            }
            
            # Make the API request
            response = requests.get(url, headers=headers, params=querystring, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Check if we have properties in the response
                if "props" in data and data["props"]:
                    all_properties = []
                    all_properties.extend(data["props"])
                    
                    # Try to fetch additional pages to get more results
                    current_page = 1
                    total_pages = data.get("totalPages", 1)
                    
                    # Fetch up to 5 pages maximum to get more properties
                    while current_page < min(total_pages, 5) and current_page < 5:
                        current_page += 1
                        querystring["page"] = str(current_page)
                        
                        try:
                            next_response = requests.get(url, headers=headers, params=querystring, timeout=10)
                            if next_response.status_code == 200:
                                next_data = next_response.json()
                                if "props" in next_data and next_data["props"]:
                                    all_properties.extend(next_data["props"])
                                else:
                                    break
                            else:
                                break
                        except:
                            break
                    
                    self.search_results = all_properties
                    
                    # Format the output
                    result_text = f"🏠 **Zillow Scout Results for {location}**\n"
                    result_text += f"**Search Criteria:** {property_type.title()} properties, ${min_price:,} - ${max_price:,}"
                    if bedrooms > 0:
                        result_text += f", {bedrooms}+ bed"
                    if bathrooms > 0:
                        result_text += f", {bathrooms}+ bath"
                    result_text += f"\n\n"
                    
                    for i, prop in enumerate(all_properties, 1):  # Show ALL properties found
                        # Extract all available property details
                        address = prop.get("address", "Address not available")
                        price = prop.get("price", "Price not listed")
                        zpid = prop.get("zpid", "")
                        
                        # Format price if it's a number
                        if isinstance(price, (int, float)):
                            formatted_price = f"${price:,}"
                        elif isinstance(price, str) and price.isdigit():
                            formatted_price = f"${int(price):,}"
                        else:
                            formatted_price = str(price)
                        
                        # Get basic property info
                        beds = prop.get("bedrooms")
                        baths = prop.get("bathrooms")
                        property_type_detail = prop.get("propertyType", "")
                        living_area = prop.get("livingArea")
                        lot_area_value = prop.get("lotAreaValue")
                        lot_area_unit = prop.get("lotAreaUnit", "")
                        
                        # Get listing details
                        listing_status = prop.get("listingStatus", "")
                        days_on_zillow = prop.get("daysOnZillow")
                        listing_subtype = prop.get("listingSubType", {})
                        is_fsba = listing_subtype.get("is_FSBA", False) if listing_subtype else False
                        contingent_type = prop.get("contingentListingType")
                        date_sold = prop.get("dateSold")
                        
                        # Get location details
                        latitude = prop.get("latitude")
                        longitude = prop.get("longitude")
                        country = prop.get("country", "")
                        currency = prop.get("currency", "USD")
                        
                        # Get media info
                        img_src = prop.get("imgSrc", "")
                        has_image = prop.get("hasImage", False)
                        
                        # Get property URL
                        property_url = prop.get("detailUrl", "")
                        if property_url and not property_url.startswith("http"):
                            property_url = f"https://www.zillow.com{property_url}"
                        
                        # Clean address for title
                        clean_address = address.replace(", ", " • ")
                        
                        # Build comprehensive property entry
                        if property_url:
                            result_text += f"### P{i} - [{clean_address}]({property_url})\n\n"
                        else:
                            result_text += f"### P{i} - {clean_address}\n\n"
                        
                        # Add property image if available
                        if img_src and has_image:
                            result_text += f"![Property Image]({img_src})\n\n"
                        
                        # Create property details table
                        result_text += "| **Property Details** | **Value** |\n"
                        result_text += "|---------------------|----------|\n"
                        
                        # Price and basic details
                        price_display = formatted_price
                        if currency and currency != "USD":
                            price_display += f" {currency}"
                        result_text += f"| **Price** | {price_display} |\n"
                        
                        # Bedroom/bathroom layout
                        if beds is not None and baths is not None:
                            result_text += f"| **Layout** | {beds} bed, {baths} bath |\n"
                        elif beds is not None:
                            result_text += f"| **Bedrooms** | {beds} |\n"
                        elif baths is not None:
                            result_text += f"| **Bathrooms** | {baths} |\n"
                        
                        # Living area (square footage)
                        if living_area:
                            result_text += f"| **Living Area** | {living_area:,} sq ft |\n"
                        
                        # Lot size
                        if lot_area_value:
                            unit = lot_area_unit if lot_area_unit else "sq ft"
                            result_text += f"| **Lot Size** | {lot_area_value:,} {unit} |\n"
                        
                        # Property type
                        if property_type_detail:
                            result_text += f"| **Property Type** | {property_type_detail} |\n"
                        
                        # Listing status and market info
                        if listing_status:
                            result_text += f"| **Status** | {listing_status} |\n"
                        
                        if days_on_zillow is not None:
                            result_text += f"| **Days on Zillow** | {days_on_zillow} |\n"
                        
                        # Special listing indicators
                        if is_fsba:
                            result_text += f"| **For Sale by Agent** | Yes |\n"
                        
                        if contingent_type:
                            result_text += f"| **Contingent Type** | {contingent_type} |\n"
                        
                        if date_sold:
                            result_text += f"| **Date Sold** | {date_sold} |\n"
                        
                        # Location coordinates
                        if latitude is not None and longitude is not None:
                            result_text += f"| **Coordinates** | {latitude:.4f}, {longitude:.4f} |\n"
                            # Add Google Maps link
                            maps_url = f"https://www.google.com/maps?q={latitude},{longitude}"
                            result_text += f"| **Google Maps** | [View Location]({maps_url}) |\n"
                        
                        # Country if not US
                        if country and country.upper() != "USA":
                            result_text += f"| **Country** | {country} |\n"
                        
                        # Zillow Property ID for reference
                        if zpid:
                            result_text += f"| **Listing ID** | {zpid} |\n"
                        
                        result_text += f"| **Source** | Zillow |\n\n"
                        result_text += "---\n\n"
                    
                    return result_text
                    
                else:
                    return f"No properties found for {location} with your specified criteria. Try adjusting your search parameters."
            
            elif response.status_code == 429:
                return "⚠️ **API Rate Limit Reached**\n\nThe Zillow API has rate limits. Please try again in a few moments, or consider using fewer requests."
            
            elif response.status_code == 403:
                return "⚠️ **API Access Required**\n\nTo use the full Zillow API functionality, you would need a RapidAPI key. This is a demo showing the structure and format of results."
            
            else:
                return f"Error accessing Zillow API: HTTP {response.status_code}. Please try again later."
                
        except requests.RequestException as e:
            return f"Network error when accessing Zillow API: {str(e)}"
        except Exception as e:
            return f"Error scouting properties: {str(e)}\n{traceback.format_exc()}"



if __name__ == "__main__":
    hyphae.run(RealtorApp())
