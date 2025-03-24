import requests
import time
import json
import logging
import string

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("autocomplete_extraction.log"),
        logging.StreamHandler()
    ]
)

class AutocompleteExtractor:
    def __init__(self, base_url, max_results=50, rate_limit_delay=0.5):
        self.base_url = base_url
        self.max_results = max_results
        self.rate_limit_delay = rate_limit_delay
        self.discovered_names = set()
        self.request_count = 0
        self.consecutive_success = 0
        self.adaptive_delay = rate_limit_delay
        self.max_adaptive_delay = 2.0  # Maximum delay in seconds
        self.min_adaptive_delay = 0.5  # Minimum delay in seconds
        
        # Define alphanumeric characters (0-9, a-z)
        # Numbers have higher priority than letters (per ASCII ordering)
        self.charset = string.digits + string.ascii_lowercase
        
    def get_autocomplete_suggestions(self, query, retry_count=0, max_retries=5):
        # Updated to use the v2 API endpoint
        url = f"{self.base_url}/v2/autocomplete?query={query}&max_results={self.max_results}"
        
        try:
            response = requests.get(url)
            self.request_count += 1
            
                            # Handle rate limiting with exponential backoff
            if response.status_code == 429:
                wait_time = min(30, 2 ** retry_count)  # Exponential backoff capped at 30 seconds
                logging.warning(f"Rate limited. Sleeping for {wait_time} seconds. (Retry {retry_count+1}/{max_retries})")
                time.sleep(wait_time)
                
                # Increase the adaptive delay
                self._adjust_delay(False)
                
                if retry_count < max_retries:
                    return self.get_autocomplete_suggestions(query, retry_count + 1, max_retries)
                else:
                    logging.error(f"Max retries reached for query '{query}'. Skipping.")
                    return []
            
            if response.status_code != 200:
                logging.error(f"Error status code: {response.status_code}")
                
                # Handle other server errors with backoff
                if response.status_code >= 500:
                    wait_time = min(10, 1 + retry_count)
                    logging.warning(f"Server error. Sleeping for {wait_time} seconds.")
                    time.sleep(wait_time)
                    
                    if retry_count < max_retries:
                        return self.get_autocomplete_suggestions(query, retry_count + 1, max_retries)
                
                return []
            
            data = response.json()
            
            if "results" in data and isinstance(data["results"], list):
                suggestions = data["results"]
                logging.info(f"Query '{query}' returned {len(suggestions)} suggestions (count: {data.get('count', 'N/A')})")
                
                if suggestions and len(suggestions) > 0:
                    logging.debug(f"First: {suggestions[0]}, Last: {suggestions[-1]}")
                
                return suggestions
            else:
                logging.warning(f"Unexpected response format: {data.keys()}")
                return []
            
        except requests.exceptions.RequestException as e:
            wait_time = min(30, 2 ** retry_count)
            logging.error(f"Request error querying '{query}': {str(e)}. Retrying in {wait_time}s")
            time.sleep(wait_time)
            
            if retry_count < max_retries:
                return self.get_autocomplete_suggestions(query, retry_count + 1, max_retries)
            else:
                logging.error(f"Max retries reached. Skipping query '{query}'")
                return []
                
        except Exception as e:
            logging.error(f"Unexpected error querying '{query}': {str(e)}")
            time.sleep(5)
            return []
    
    def crawl_autocomplete(self):
        logging.info(f"Starting extraction with max_results={self.max_results}")
        start_time = time.time()
        
        # Start with single alphanumeric characters (0-9, a-z)
        for first_char in self.charset:
            self.explore_prefix(first_char)
            
        elapsed_time = time.time() - start_time
        logging.info(f"Extraction completed in {elapsed_time:.2f} seconds")
        logging.info(f"Total API requests: {self.request_count}")
        logging.info(f"Total names discovered: {len(self.discovered_names)}")
        
        return self.discovered_names
    
    def explore_prefix(self, prefix):
        """
        Explore a prefix and all necessary follow-up prefixes.
        Takes the second letter of the last result when needed to optimize the exploration.
        Handles both numbers and letters.
        """
        logging.info(f"Processing prefix: '{prefix}'")
        
        suggestions = self.get_autocomplete_suggestions(prefix)
        
        # Add all suggestions to our discovered names
        for name in suggestions:
            self.discovered_names.add(name)
        
        # If we got exactly max_results, we need to explore further
        if len(suggestions) == self.max_results:
            last_result = suggestions[-1]
            
            if len(prefix) < len(last_result):
                # Take the next character from the last result
                next_char = last_result[len(prefix)]
                next_prefix = prefix + next_char
                self.explore_prefix(next_prefix)
                
                # Now, continue with the remaining characters of our charset
                # Start from the character after the one we just used
                for c in self.charset:
                    if c > next_char:  # Only try characters after the one we already used
                        new_prefix = prefix + c
                        self.explore_prefix(new_prefix)
            else:
                # This is an edge case - if the last result is exactly the prefix
                # Try all characters as we don't know where to go next
                for c in self.charset:
                    new_prefix = prefix + c
                    self.explore_prefix(new_prefix)
        
        # Use adaptive delay between requests
        self._adjust_delay(True)  # True indicates a successful request
        time.sleep(self.adaptive_delay)
    
    def save_results(self, output_file="discovered_names.json"):
        results = {
            "total_requests": self.request_count,
            "total_names": len(self.discovered_names),
            "names": sorted(list(self.discovered_names))
        }
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logging.info(f"Results saved to {output_file}")


    def _adjust_delay(self, success):
        """
        Adaptively adjust the delay between requests based on success or failure.
        Increases delay on failures, gradually decreases on consecutive successes.
        """
        if success:
            self.consecutive_success += 1
            # After 10 consecutive successes, slightly reduce delay
            if self.consecutive_success > 10:
                self.adaptive_delay = max(self.min_adaptive_delay, 
                                         self.adaptive_delay * 0.95)
                self.consecutive_success = 0
                logging.info(f"Reduced delay to {self.adaptive_delay:.2f}s after consecutive successes")
        else:
            # On failure, increase delay by 50% and reset success counter
            self.adaptive_delay = min(self.max_adaptive_delay,
                                     self.adaptive_delay * 1.5)
            self.consecutive_success = 0
            logging.info(f"Increased delay to {self.adaptive_delay:.2f}s after failure")


def main():
    extractor = AutocompleteExtractor(
        base_url="http://35.200.185.69:8000",  # Update with your actual API base URL
        max_results=75,  # Updated to use the correct max_results value
        rate_limit_delay=0.5  # Start with a higher base delay
    )
    
    all_names = extractor.crawl_autocomplete()
    extractor.save_results()
    
    print(f"Extraction complete. Found {len(all_names)} names.")
    print(f"Made {extractor.request_count} API requests.")


if __name__ == "__main__":
    main()