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
    def __init__(self, base_url, max_results=50, rate_limit_delay=0.2):
        self.base_url = base_url
        self.max_results = max_results
        self.rate_limit_delay = rate_limit_delay
        self.discovered_names = set()
        self.request_count = 0
        
    def get_autocomplete_suggestions(self, query):
        url = f"{self.base_url}/v1/autocomplete?query={query}&max_results={self.max_results}"
        
        try:
            response = requests.get(url)
            self.request_count += 1
            
            # Handle rate limiting
            if response.status_code == 429:
                logging.warning(f"Rate limited. Sleeping for 1 second.")
                time.sleep(1)
                return self.get_autocomplete_suggestions(query)
            
            if response.status_code != 200:
                logging.error(f"Error status code: {response.status_code}")
                time.sleep(1)
                return []
            
            data = response.json()
            
            if "results" in data and isinstance(data["results"], list):
                suggestions = data["results"]
                logging.info(f"Query '{query}' returned {len(suggestions)} suggestions")
                
                if suggestions and len(suggestions) > 0:
                    logging.debug(f"First: {suggestions[0]}, Last: {suggestions[-1]}")
                
                return suggestions
            else:
                logging.warning(f"Unexpected response format: {data.keys()}")
                return []
            
        except Exception as e:
            logging.error(f"Error querying '{query}': {str(e)}")
            time.sleep(2)
            return []
    
    def crawl_autocomplete(self):
        logging.info(f"Starting extraction with max_results={self.max_results}")
        start_time = time.time()
        
        # Start with single letters
        for first_letter in string.ascii_lowercase:
            self.explore_prefix(first_letter)
            
        elapsed_time = time.time() - start_time
        logging.info(f"Extraction completed in {elapsed_time:.2f} seconds")
        logging.info(f"Total API requests: {self.request_count}")
        logging.info(f"Total names discovered: {len(self.discovered_names)}")
        
        return self.discovered_names
    
    def explore_prefix(self, prefix):
        """
        Explore a prefix and all necessary follow-up prefixes.
        Takes the second letter of the last result when needed to optimize the exploration.
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
                # Take the next letter from the last result
                next_letter = last_result[len(prefix)]
                next_prefix = prefix + next_letter
                self.explore_prefix(next_prefix)
                
                # Now, continue with the remaining letters of the alphabet
                # Start from the letter after the one we just used
                for c in string.ascii_lowercase:
                    if c > next_letter:  # Only try letters after the one we already used
                        new_prefix = prefix + c
                        self.explore_prefix(new_prefix)
            else:
                # This is an edge case - if the last result is exactly the prefix
                # Try all letters as we don't know where to go next
                for c in string.ascii_lowercase:
                    new_prefix = prefix + c
                    self.explore_prefix(new_prefix)
        
        time.sleep(self.rate_limit_delay)
    
    def save_results(self, output_file="discovered_names.json"):
        results = {
            "total_requests": self.request_count,
            "total_names": len(self.discovered_names),
            "names": sorted(list(self.discovered_names))
        }
        
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logging.info(f"Results saved to {output_file}")


def main():
    extractor = AutocompleteExtractor(
        base_url="http://35.200.185.69:8000",
        max_results=50,
        rate_limit_delay=0.2
    )
    
    all_names = extractor.crawl_autocomplete()
    extractor.save_results()
    
    print(f"Extraction complete. Found {len(all_names)} names.")
    print(f"Made {extractor.request_count} API requests.")


if __name__ == "__main__":
    main()