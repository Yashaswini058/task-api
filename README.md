# Autocomplete API Name Extractor

A comprehensive solution for extracting all possible names from an undocumented autocomplete API running at http://35.200.185.69:8000. This project includes three versions (v1, v2, and v3) of the extractor with progressive enhancements.

## Overview

The challenge required extracting all possible names from an autocomplete API with no official documentation. Through exploration and reverse engineering, the project evolved across three major versions, each with different strategies to handle the API's constraints.

## API Discoveries

Initial exploration revealed several key insights about the API:

1. The API has multiple versions: `/v1/autocomplete`, `/v2/autocomplete`, and `/v3/autocomplete`
2. By default, the API only returns 10 results per query
3. Through brute force exploration, we discovered the undocumented `max_results` parameter
4. Each API version has different maximum result limits:
   - v1: 50 results maximum
   - v2: 75 results maximum
   - v3: 100 results maximum
5. The API implements rate limiting, returning a 429 status code when too many requests are made
6. Results include alphanumeric characters (0-9, a-z) with potential for special characters

## Extraction Strategies

### Version 1: Basic Recursive Exploration

The initial solution uses a recursive strategy:

1. Start with single characters (a-z)
2. For each prefix that returns exactly the maximum number of results:
   - Take the next character from the last result 
   - Create a new prefix with this next character
   - Recursively explore this new prefix
   - Also explore all alphabetically subsequent characters
3. Uses fixed delays between requests to respect rate limiting

**Key Features:**
- Efficient prefix exploration using the last result's next character
- Simple rate limit handling with fixed delay
- Alphabetic character set (a-z)

### Version 2: Enhanced Robustness and Adaptivity

Version 2 builds on the foundation of v1 with significant enhancements:

1. Expanded to use the v2 API endpoint with higher result limit (75)
2. Added exponential backoff for rate limit handling
3. Implemented adaptive delays that adjust based on request success/failure
4. Expanded character set to include both letters and digits (0-9, a-z)
5. More comprehensive error handling and retry logic

**Key Features:**
- Adaptive delay algorithm that learns from rate limiting patterns
- Expanded character set with numbers having higher priority
- Exponential backoff with capped maximum wait time
- More robust error handling and logging

### Version 3: Multithreaded with Sophisticated Queueing

Version 3 represents a complete architecture redesign for maximum efficiency:

1. Uses v3 API endpoint with 100 result limit 
2. Implements multithreaded exploration with thread pool
3. Uses a priority queue system to optimize exploration paths
4. Adds checkpointing for resuming interrupted extractions
5. Implements dynamic rate limiting based on statistical analysis
6. Expanded character set to include special characters
7. Advanced monitoring with detailed progress statistics

**Key Features:**
- Concurrent exploration with configurable thread pool
- Checkpoint system for fault tolerance
- Priority-based queuing that prioritizes shorter prefixes
- Thread-safe data structures for concurrent operations
- Comprehensive statistics on prefix length efficacy 
- Adaptive delays that vary based on prefix length
- Sophisticated rate limit handling with exponential backoff and jitter

## Implementation Details

The core algorithm across all versions uses a modified breadth-first search with an optimization that:

1. Prioritizes the next character from the last result of a maxed-out query
2. Explores remaining characters in order, skipping those already covered
3. Handles edge cases like when the last result is equal to the prefix

As the versions progress, additional features are added:
- Thread safety mechanisms in v3
- Adaptive delay algorithms that become increasingly sophisticated
- Priority-based exploration that focuses on most promising paths first
- Checkpointing for resilience against interruptions

## Results and Performance

The extraction performance improved substantially across versions:

| Version | API Limit | Threading | Names Found | Requests | Efficiency |
|---------|-----------|-----------|-------------|----------|------------|
| v1      | 50        | Single    | ~18,600     | ~1,950   | ~9.5       |
| v2      | 75        | Single    | ~25,000     | ~1,650   | ~15.2      |
| v3      | 100       | Multi     |             |          |            |

The efficiency metric (names per request) shows significant improvement with each version.

## Challenges and Solutions

1. **Challenge**: API returns limited results per query
   **Solution**: Implemented increasingly sophisticated prefix exploration strategies

2. **Challenge**: Rate limiting restricts request frequency
   **Solution**: Evolved from fixed delays (v1) to adaptive delays (v2) to statistical modeling with variable delays (v3)

3. **Challenge**: Extraction process is time-consuming
   **Solution**: Added multithreading and checkpointing in v3 for resilience and performance

4. **Challenge**: Unknown character set for names
   **Solution**: Progressively expanded character set from a-z to include digits and special characters

5. **Challenge**: Need to minimize API calls
   **Solution**: Optimized search path by using the last result's next character and priority queuing

## Running the Code

```bash
# Run version 1 (basic)
python v1_extractor.py

# Run version 2 (enhanced)
python v2_extractor.py

# Run version 3 (multithreaded)
python v3_extractor.py
```

## Configuration Options

### Version 1
- `max_results`: Maximum results per query (default: 50)
- `rate_limit_delay`: Fixed delay between requests (default: 0.5s)

### Version 2
- `max_results`: Maximum results per query (default: 75)
- `rate_limit_delay`: Initial delay between requests (default: 0.5s)
- `adaptive_delay`: Dynamically adjusted delay (min: 0.5s, max: 2.0s)

### Version 3
- `max_results`: Maximum results per query (default: 100)
- `rate_limit_delay`: Initial delay between requests (default: 1.0s)
- `max_workers`: Number of concurrent threads (default: 10)
- `checkpoint_interval`: Save frequency (default: 200 requests)
- `adaptive_delay`: Dynamically adjusted delay (min: 0.8s, max: 3.0s)

## Conclusion

This project demonstrates an evolutionary approach to solving the challenge of extracting all names from an autocomplete API. By progressively refining the strategy from a simple recursive exploration to a sophisticated multithreaded system with adaptive rate limiting, the solution achieves both completeness and efficiency.

The key innovation across all versions is the optimization of using the last result's next character to inform the search path, which dramatically reduces the number of API calls needed compared to a brute force approach of trying all possible character combinations.

Version 3 represents the most sophisticated solution, with multithreading, checkpointing, and priority-based exploration that can efficiently extract the complete set of names while respecting API constraints.
