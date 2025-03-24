import requests
import time
import json
import logging
import string
import threading
import queue
import os
import random
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("autocomplete_extraction_v3.log"),
        logging.StreamHandler()
    ]
)

class AutocompleteExtractor:
    def __init__(self, base_url, max_results=100, rate_limit_delay=1.0, max_workers=5, checkpoint_interval=200):
        self.base_url = base_url
        self.max_results = max_results
        self.rate_limit_delay = rate_limit_delay
        self.max_workers = max_workers
        self.checkpoint_interval = checkpoint_interval
        
        # Thread-safe data structures
        self.discovered_names = set()
        self.names_lock = threading.Lock()
        self.request_count = 0
        self.request_count_lock = threading.Lock()
        self.explored_prefixes = set()
        self.explored_prefixes_lock = threading.Lock()
        
        # Queue for prefixes to explore
        self.prefix_queue = queue.PriorityQueue()  # Use priority queue to explore shorter prefixes first
        
        # Thread management
        self.active_threads = 0
        self.active_threads_lock = threading.Lock()
        
        # Rate limiting
        self.adaptive_delay = rate_limit_delay
        self.max_adaptive_delay = 3.0  # Maximum delay in seconds
        self.min_adaptive_delay = 0.8  # Higher minimum delay to avoid rate limits
        self.delay_lock = threading.Lock()
        self.rate_limit_counters = {"success": 0, "failure": 0}
        
        # Checkpoint system
        self.checkpoint_file = "autocomplete_checkpoint_v3.json"
        
        # Define initial character set with optimization - start with most common characters first
        # Focus on alphanumeric first, then special chars if needed
        self.charset = string.digits + string.ascii_lowercase
        # We add special characters at a lower priority - the API likely prioritizes alphanumeric chars
        self.special_charset = string.punctuation.replace('\\', '').replace('"', '').replace('\'', '')
        self.full_charset = self.charset + self.special_charset
        
        # Statistics
        self.start_time = time.time()
        self.last_status_time = time.time()
        self.last_checkpoint_time = time.time()
        
        # Success rate tracking by prefix length for adaptive strategy
        self.prefix_length_stats = {}
        
    def get_autocomplete_suggestions(self, query, retry_count=0, max_retries=8):
        """
        Get autocomplete suggestions with enhanced rate limit handling
        """
        # Use a session for connection pooling
        session = requests.Session()
        
        try:
            # Add small jitter to request timing
            jitter = random.uniform(0, 0.3)
            time.sleep(jitter)
            
            # Use the v3 API endpoint with longer timeout
            url = f"{self.base_url}/v3/autocomplete?query={query}&max_results={self.max_results}"
            
            headers = {
                'User-Agent': f'AutocompleteExtractor/1.0 (Query: {query[:10]}...)'
            }
            
            response = session.get(url, headers=headers, timeout=(5, 30))
            
            with self.request_count_lock:
                self.request_count += 1
                # Save checkpoint periodically based on both time and request count
                current_time = time.time()
                if (self.request_count % self.checkpoint_interval == 0) or (current_time - self.last_checkpoint_time > 300):  # 5 minutes
                    self._save_checkpoint()
                    self.last_checkpoint_time = current_time
            
            # Handle rate limiting with exponential backoff
            if response.status_code == 429:
                # Increase the failure counter
                with self.delay_lock:
                    self.rate_limit_counters["failure"] += 1
                
                # Calculate wait time with exponential backoff and randomized jitter
                wait_time = min(90, (2 ** retry_count) * (1 + random.uniform(0, 0.3)))
                logging.warning(f"Rate limited. Sleeping for {wait_time:.2f} seconds. (Retry {retry_count+1}/{max_retries})")
                time.sleep(wait_time)
                
                # Increase the adaptive delay significantly
                self._adjust_delay(False)
                
                if retry_count < max_retries:
                    # Close the session before recursive call
                    session.close()
                    return self.get_autocomplete_suggestions(query, retry_count + 1, max_retries)
                else:
                    logging.error(f"Max retries reached for query '{query}'. Skipping.")
                    session.close()
                    return []
            
            if response.status_code != 200:
                logging.error(f"Error status code: {response.status_code} for query '{query}'")
                
                # Handle other server errors with backoff
                if response.status_code >= 500:
                    wait_time = min(45, (1 + retry_count) * 5)
                    logging.warning(f"Server error. Sleeping for {wait_time} seconds.")
                    time.sleep(wait_time)
                    
                    if retry_count < max_retries:
                        session.close()
                        return self.get_autocomplete_suggestions(query, retry_count + 1, max_retries)
                
                session.close()
                return []
            
            data = response.json()
            
            if "results" in data and isinstance(data["results"], list):
                suggestions = data["results"]
                count = data.get('count', 'N/A')
                logging.info(f"Query '{query}' returned {len(suggestions)} suggestions (count: {count})")
                
                if suggestions and len(suggestions) > 0:
                    logging.debug(f"First: {suggestions[0]}, Last: {suggestions[-1]}")
                
                # Update prefix length stats
                prefix_len = len(query)
                if prefix_len not in self.prefix_length_stats:
                    self.prefix_length_stats[prefix_len] = {"success": 0, "queries": 0}
                self.prefix_length_stats[prefix_len]["queries"] += 1
                if len(suggestions) > 0:
                    self.prefix_length_stats[prefix_len]["success"] += 1
                
                # Successful request, adjust delay
                with self.delay_lock:
                    self.rate_limit_counters["success"] += 1
                self._adjust_delay(True)
                
                session.close()
                return suggestions
            else:
                logging.warning(f"Unexpected response format: {data.keys()}")
                session.close()
                return []
            
        except requests.exceptions.RequestException as e:
            # Exponential backoff for network errors
            wait_time = min(45, (2 ** retry_count) * 2)
            logging.error(f"Request error querying '{query}': {str(e)}. Retrying in {wait_time}s")
            time.sleep(wait_time)
            
            if retry_count < max_retries:
                # Clean up session before recursing
                try:
                    session.close()
                except:
                    pass
                return self.get_autocomplete_suggestions(query, retry_count + 1, max_retries)
            else:
                logging.error(f"Max retries reached. Skipping query '{query}'")
                try:
                    session.close()
                except:
                    pass
                return []
                
        except Exception as e:
            logging.error(f"Unexpected error querying '{query}': {str(e)}")
            time.sleep(8)  # Longer sleep for unexpected errors
            try:
                session.close()
            except:
                pass
            return []
    
    def crawl_autocomplete(self):
        """
        Main crawling function that controls the threadpool and manages the work queue
        """
        logging.info(f"Starting extraction with max_results={self.max_results} and {self.max_workers} workers")
        logging.info(f"Initial delay: {self.adaptive_delay}s, Min: {self.min_adaptive_delay}s, Max: {self.max_adaptive_delay}s")
        logging.info(f"Primary character set: {self.charset}")
        logging.info(f"Special characters: {self.special_charset}")
        
        self.start_time = time.time()
        
        # Try to load checkpoint first
        if self._load_checkpoint():
            logging.info(f"Resumed from checkpoint with {len(self.discovered_names)} names and {len(self.explored_prefixes)} explored prefixes")
        else:
            # Initialize with single character prefixes - add as priority items (priority, item)
            # Lower number = higher priority
            
            # First add all alphanumeric characters (higher priority)
            for first_char in self.charset:
                self.prefix_queue.put((1, first_char))  # Priority 1 for single-char alphanumeric prefixes
            
            # Then add special characters (lower priority)
            for first_char in self.special_charset:
                self.prefix_queue.put((2, first_char))  # Priority 2 for special characters
                
            logging.info(f"Starting fresh with {self.prefix_queue.qsize()} initial prefixes")
        
        try:
            # Create a thread pool
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Start worker threads
                workers = []
                for _ in range(self.max_workers):
                    workers.append(executor.submit(self.worker))
                    
                # Monitor progress and provide status updates
                while not self.prefix_queue.empty() or self.active_threads > 0:
                    queue_size = self.prefix_queue.qsize()
                    with self.active_threads_lock:
                        active = self.active_threads
                    
                    with self.request_count_lock:
                        requests = self.request_count
                    
                    with self.names_lock:
                        names = len(self.discovered_names)
                    
                    current_time = time.time()
                    elapsed = current_time - self.start_time
                    
                    # Log status update every 30 seconds
                    if current_time - self.last_status_time > 30:
                        self.last_status_time = current_time
                        
                        # Calculate rate
                        minutes = elapsed / 60
                        names_per_minute = names / max(minutes, 0.01)
                        requests_per_minute = requests / max(minutes, 0.01)
                        
                        logging.info(f"Status: {names} names found, {requests} requests made, {queue_size} prefixes queued")
                        logging.info(f"Rate: {names_per_minute:.1f} names/min, {requests_per_minute:.1f} requests/min")
                        logging.info(f"Current delay: {self.adaptive_delay:.2f}s, Success/Failure: {self.rate_limit_counters['success']}/{self.rate_limit_counters['failure']}")
                        
                        # Log prefix length statistics
                        if self.prefix_length_stats:
                            logging.info("Prefix length statistics:")
                            for length, stats in sorted(self.prefix_length_stats.items()):
                                if stats["queries"] > 0:
                                    success_rate = (stats["success"] / stats["queries"]) * 100
                                    logging.info(f"  Length {length}: {stats['success']}/{stats['queries']} ({success_rate:.1f}% success)")
                    
                    time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Received keyboard interrupt, saving checkpoint before exit")
            self._save_checkpoint()
        
        elapsed_time = time.time() - self.start_time
        
        # Final status
        minutes = elapsed_time / 60
        names_per_minute = len(self.discovered_names) / max(minutes, 0.01)
        requests_per_minute = self.request_count / max(minutes, 0.01)
        
        logging.info(f"Extraction completed in {elapsed_time:.2f} seconds ({minutes:.1f} minutes)")
        logging.info(f"Total API requests: {self.request_count}")
        logging.info(f"Total names discovered: {len(self.discovered_names)}")
        logging.info(f"Final rate: {names_per_minute:.1f} names/min, {requests_per_minute:.1f} requests/min")
        
        # Final checkpoint
        self._save_checkpoint()
        
        return self.discovered_names
    
    def worker(self):
        """Worker thread that processes prefixes from the queue"""
        with self.active_threads_lock:
            self.active_threads += 1
        
        try:
            while True:
                try:
                    # Get a prefix from the queue with a timeout
                    priority, prefix = self.prefix_queue.get(timeout=5)
                    
                    # Check if we've already explored this prefix (could happen if loaded from checkpoint)
                    with self.explored_prefixes_lock:
                        if prefix in self.explored_prefixes:
                            self.prefix_queue.task_done()
                            continue
                    
                    try:
                        # Process this prefix
                        self.explore_prefix(prefix)
                        
                        # Mark this prefix as explored
                        with self.explored_prefixes_lock:
                            self.explored_prefixes.add(prefix)
                    except Exception as e:
                        logging.error(f"Error exploring prefix '{prefix}': {str(e)}")
                    finally:
                        # Mark this prefix as done
                        self.prefix_queue.task_done()
                        
                        # Apply adaptive delay between requests
                        with self.delay_lock:
                            delay = self.adaptive_delay
                            
                            # Apply shorter delays for longer prefixes (they're less likely to hit rate limits)
                            prefix_len = len(prefix)
                            if prefix_len > 3:
                                delay = max(self.min_adaptive_delay, delay * 0.8)
                            
                        time.sleep(delay)
                        
                except queue.Empty:
                    # Queue empty, check if all other workers are also idle
                    if self.prefix_queue.empty():
                        break
        finally:
            with self.active_threads_lock:
                self.active_threads -= 1
    
    def explore_prefix(self, prefix):
        """
        Explore a prefix and queue follow-up prefixes when needed.
        Thread-safe version with priority queue and improved branching strategy.
        """
        logging.info(f"Processing prefix: '{prefix}'")
        
        suggestions = self.get_autocomplete_suggestions(prefix)
        
        # Add all suggestions to our discovered names (thread-safe)
        with self.names_lock:
            for name in suggestions:
                self.discovered_names.add(name)
        
        # If we got max_results, we need to explore further by branching out
        if len(suggestions) == self.max_results:
            last_result = suggestions[-1]
            prefix_len = len(prefix)
            
            if prefix_len < len(last_result):
                # KEY OPTIMIZATION: Take the next character from the last result
                next_char = last_result[prefix_len]
                next_prefix = prefix + next_char
                
                # Avoid re-queuing already explored prefixes
                with self.explored_prefixes_lock:
                    if next_prefix not in self.explored_prefixes:
                        # Highest priority for the direct path based on last result
                        self.prefix_queue.put((prefix_len, next_prefix))  # Highest priority
                
                # Continue with the remaining characters of our charset
                # Start from the character AFTER the one we just used
                charset_to_use = self.full_charset
                for c in charset_to_use:
                    if c > next_char:  # Only try characters after the one we already used
                        new_prefix = prefix + c
                        with self.explored_prefixes_lock:
                            if new_prefix not in self.explored_prefixes:
                                # Lower priority (higher number) for other branches
                                # Use even lower priority for special chars
                                priority_boost = 5 if c in self.charset else 10
                                self.prefix_queue.put((prefix_len + priority_boost, new_prefix))
            else:
                # This is an edge case - if the last result is exactly the prefix
                # Try all characters as we don't know where to go next
                for c in self.full_charset:
                    new_prefix = prefix + c
                    with self.explored_prefixes_lock:
                        if new_prefix not in self.explored_prefixes:
                            # Use different priorities for alphanumeric vs special chars
                            priority_boost = 5 if c in self.charset else 10
                            self.prefix_queue.put((prefix_len + priority_boost, new_prefix))
    
    def save_results(self, output_file="discovered_names_v3.json"):
        """Save the final results to a JSON file"""
        results = {
            "total_requests": self.request_count,
            "total_names": len(self.discovered_names),
            "names": sorted(list(self.discovered_names))
        }
        
        # Write to temp file first to prevent corruption on interruption
        temp_file = f"{output_file}.tmp"
        with open(temp_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        # Rename to final filename
        os.replace(temp_file, output_file)
        
        logging.info(f"Results saved to {output_file}")

    def _adjust_delay(self, success):
        """
        Adaptively adjust the delay between requests based on success or failure patterns.
        Uses a more conservative approach to reduce rate limit issues.
        """
        with self.delay_lock:
            if success:
                # Calculate success ratio over recent history
                success_ratio = self.rate_limit_counters["success"] / max(1, self.rate_limit_counters["success"] + self.rate_limit_counters["failure"])
                
                # Only decrease if we have a good success rate (>85%) and significant sample
                if success_ratio > 0.85 and self.rate_limit_counters["success"] > 30:
                    # Decrease very gradually (by 3%)
                    self.adaptive_delay = max(self.min_adaptive_delay, 
                                             self.adaptive_delay * 0.97)
                    # Reset the counters but keep some history
                    self.rate_limit_counters["success"] = 15
                    self.rate_limit_counters["failure"] = 2
                    logging.info(f"Decreased delay to {self.adaptive_delay:.2f}s after consistent success")
            else:
                # On failure, increase delay significantly and reset success counter
                self.adaptive_delay = min(self.max_adaptive_delay,
                                         self.adaptive_delay * 1.5)
                # Reset success counter to be conservative
                self.rate_limit_counters["success"] = 0
                logging.info(f"Increased delay to {self.adaptive_delay:.2f}s after failure")

    def _save_checkpoint(self):
        """Save current progress to a checkpoint file"""
        try:
            checkpoint_data = {
                "discovered_names": list(self.discovered_names),
                "explored_prefixes": list(self.explored_prefixes),
                "request_count": self.request_count,
                "timestamp": time.time(),
                "prefix_length_stats": self.prefix_length_stats
            }
            
            # Write to temp file first to prevent corruption
            temp_file = f"{self.checkpoint_file}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(checkpoint_data, f)
            
            # Rename to final filename
            os.replace(temp_file, self.checkpoint_file)
            
            logging.info(f"Checkpoint saved with {len(self.discovered_names)} names and {len(self.explored_prefixes)} explored prefixes")
            return True
        except Exception as e:
            logging.error(f"Error saving checkpoint: {str(e)}")
            return False
    
    def _load_checkpoint(self):
        """Load the checkpoint file if available"""
        if not os.path.exists(self.checkpoint_file):
            return False
            
        try:
            with open(self.checkpoint_file, 'r') as f:
                checkpoint_data = json.load(f)
            
            # Restore discovered names
            self.discovered_names = set(checkpoint_data.get("discovered_names", []))
            
            # Restore explored prefixes
            self.explored_prefixes = set(checkpoint_data.get("explored_prefixes", []))
            
            # Restore request count
            self.request_count = checkpoint_data.get("request_count", 0)
            
            # Restore prefix length stats if available
            if "prefix_length_stats" in checkpoint_data:
                self.prefix_length_stats = checkpoint_data["prefix_length_stats"]
            
            # Queue unexplored next level prefixes using smart prioritization
            priority_base = 1000  # Start with a high priority base to ensure existing items are processed first
            
            # Group prefixes by length for better prioritization
            prefix_by_length = {}
            for prefix in self.explored_prefixes:
                prefix_len = len(prefix)
                if prefix_len not in prefix_by_length:
                    prefix_by_length[prefix_len] = []
                prefix_by_length[prefix_len].append(prefix)
            
            # Process shorter prefixes first
            for prefix_len in sorted(prefix_by_length.keys()):
                for prefix in prefix_by_length[prefix_len]:
                    for char in self.charset:
                        new_prefix = prefix + char
                        if new_prefix not in self.explored_prefixes:
                            # Higher priority (lower number) for shorter prefixes
                            self.prefix_queue.put((prefix_len + 1, new_prefix))
            
            logging.info(f"Checkpoint loaded with {len(self.discovered_names)} names")
            logging.info(f"Queued {self.prefix_queue.qsize()} prefixes for exploration")
            
            return True
        except Exception as e:
            logging.error(f"Error loading checkpoint: {str(e)}")
            return False


def main():
    extractor = AutocompleteExtractor(
        base_url="http://35.200.185.69:8000",
        max_results=100,             # v3 API supports 100 results
        rate_limit_delay=1.0,        # Start with a moderate base delay
        max_workers=10,               
        checkpoint_interval=200      # Save checkpoint every 200 requests
    )
    
    all_names = extractor.crawl_autocomplete()
    extractor.save_results()
    
    print(f"Extraction complete. Found {len(all_names)} names.")
    print(f"Made {extractor.request_count} API requests.")
    
    # Calculate efficiency
    if extractor.request_count > 0:
        efficiency = len(all_names) / extractor.request_count
        print(f"Efficiency: {efficiency:.2f} names per request")


if __name__ == "__main__":
    main()