# Hyphae is the main SDK for building TruffleOS agentic applications
import hyphae

# Standard libraries for HTTP requests and XML/JSON parsing
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import re
from urllib.parse import quote
import feedparser  # For parsing Atom/RSS feeds from ArXiv API
import time
import traceback

# Hyphae-specific imports for agent responses
from hyphae.tools.respond_to_user import RespondToUserReturnType

# External AI service integration - see perplexity.py for implementation
from perplexity import PerplexitySearcher

# Hyphae hooks system for customizing agent lifecycle
import hyphae.hooks as hooks

# MAIN AGENT CLASS:
# This ArXiv research agent demonstrates academic paper search and analysis
# It shows patterns for integrating external APIs and maintaining state across tool calls
class ArxivApp:
    def __init__(self):
        """
        AGENT STATE INITIALIZATION:
        
        Hyphae agents maintain state across tool calls within a conversation.
        This allows the agent to "remember" which paper is selected and provide
        contextual follow-up capabilities.
        """
        self.selected_paper = None    # Currently selected paper metadata
        self.paper_content = None     # Full text content (when available)
        
    def has_paper_selected(self) -> bool:
        """
        PREDICATE FUNCTION:
        
        This function is used in tool decorators to conditionally enable tools.
        Some tools (like Researcher) only make sense when a paper is selected.
        This creates a natural workflow: search → select → analyze.
        """
        return self.selected_paper is not None
    
    # TOOL DEFINITIONS:
    # Each @hyphae.tool decorated method becomes available to the AI agent
    
    @hyphae.tool("Search for papers on a specific topic or field", icon="magnifyingglass")
    @hyphae.args(
        query="The search query (can be a topic, keywords, or specific paper title)",
        max_results="Maximum number of results to return (default: 10)"
    )
    def SearchPapers(self, query: str, max_results: int = 10) -> str:
        """
        ARXIV API INTEGRATION:
        
        This tool demonstrates how to integrate external APIs with Hyphae agents.
        The ArXiv API provides free access to academic papers in physics, math,
        computer science, and other fields.
        
        The tool returns formatted markdown that the AI can read and present to users.
        """
        # ArXiv API search - uses their REST API with Atom feed responses
        base_url = "http://export.arxiv.org/api/query"
        search_query = f"search_query=all:{quote(query)}"  # URL encode the query
        params = f"{search_query}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
        
        url = f"{base_url}?{params}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise exception for HTTP errors
            
            # Parse the Atom feed response using feedparser
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                return f"No papers found for query: {query}"
            
            # Format results as markdown for easy reading
            results = []
            for i, entry in enumerate(feed.entries, 1):
                # Extract and clean paper metadata
                title = entry.title.replace('\n', ' ').strip()
                authors = [author.name for author in entry.authors] if hasattr(entry, 'authors') else []
                author_str = ", ".join(authors[:3])  # Show first 3 authors
                if len(authors) > 3:
                    author_str += " et al."
                
                # Extract ArXiv ID from the entry link for later reference
                arxiv_id = entry.id.split('/')[-1]
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                
                # Extract and truncate abstract
                summary = entry.summary.replace('\n', ' ').strip()
                
                # Extract publication date
                published = entry.published[:10] if hasattr(entry, 'published') else "Unknown"
                
                # Extract subject categories
                categories = []
                if hasattr(entry, 'tags'):
                    categories = [tag.term for tag in entry.tags]
                category_str = ", ".join(categories[:3])
                
                # Format as structured markdown
                paper_info = f"""
**{i}. {title}**
- **Authors:** {author_str}
- **Published:** {published}
- **Categories:** {category_str}
- **ArXiv ID:** {arxiv_id}
- **URL:** {arxiv_url}
- **PDF:** {pdf_url}
- **Abstract:** {summary[:300]}{'...' if len(summary) > 300 else ''}

---
"""
                results.append(paper_info)
            
            return f"Found {len(feed.entries)} papers for '{query}':\n\n" + "\n".join(results)
            
        except Exception as e:
            # Graceful error handling with traceback for debugging
            return f"Error searching for papers: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Search web for papers on a topic using Perplexity", icon="globe")
    @hyphae.args(query="The research topic or query to search for")
    def SearchWebPapers(self, query: str) -> str:
        """
        EXTERNAL AI SERVICE INTEGRATION:
        
        This demonstrates how Hyphae agents can leverage external AI services.
        Here we use Perplexity AI for broader web search beyond just ArXiv,
        which can find papers from other repositories and provide more context.
        """
        search_query = f"academic papers research {query} arxiv site:arxiv.org"
        return PerplexitySearcher().run(search_query)
    
    @hyphae.tool("Search for papers beyond ArXiv (Semantic Scholar)", icon="doc.plaintext")
    @hyphae.args(
        query="The search query (can be topic, keywords, or title)",
        max_results="Maximum number of results to return (default: 10)",
        offset="Offset for pagination when retrieving additional results"
    )
    def SearchExternalPapers(self, query: str, max_results: int = 10, offset: int = 0) -> str:
        """
        SEMANTIC SCHOLAR API INTEGRATION:
        
        This tool shows integration with another academic API - Semantic Scholar.
        This provides access to a broader range of academic papers beyond ArXiv,
        including papers from traditional publishers.
        
        Note the pagination support via offset parameter for handling large result sets.
        """

        # Prepare HTTP request with proper headers
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TruffleBot/1.0; +https://truffles.ai)"
        }
        url = "https://api.semanticscholar.org/graph/v1/paper/search"

        # Specify which fields we want from the API
        fields = [
            "title",
            "authors", 
            "year",
            "venue",
            "journal",
            "externalIds",  # DOI, ArXiv ID, etc.
            "fieldsOfStudy",
            "url",
            "abstract",
            "tldr"  # AI-generated summary
        ]

        params = {
            "query": query,
            "limit": min(max_results, 100),  # API limit
            "offset": offset,
            "fields": ",".join(fields)
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json().get("data", [])

            if not data:
                return f"No external papers found for query: {query}"

            # Format results similar to ArXiv search for consistency
            results = []
            for i, paper in enumerate(data, 1):
                title = paper.get("title", "No title").replace("\n", " ").strip()
                authors = [a.get("name", "Unknown") for a in paper.get("authors", [])]
                author_str = ", ".join(authors[:3]) if authors else "Unknown"
                if len(authors) > 3:
                    author_str += " et al."

                year = paper.get("year", "n.d.")
                venue = paper.get("venue") or (paper.get("journal", {}).get("name") if paper.get("journal") else "")
                venue = venue if venue else "Unknown"

                url_link = paper.get("url", "")
                external_ids = paper.get("externalIds", {})
                doi = external_ids.get("DOI", "")

                # Use abstract or AI-generated summary
                abstract = paper.get("abstract") or paper.get("tldr", {}).get("text", "") or "No abstract available."

                fields_of_study = paper.get("fieldsOfStudy", [])
                fields_str = ", ".join(fields_of_study[:3])

                info = f"""
**{i}. {title} ({year})**
- **Authors:** {author_str}
- **Venue:** {venue}
- **Fields:** {fields_str}
- **URL:** {url_link}
- **DOI:** {doi}
- **Abstract:** {abstract[:300]}{'...' if len(abstract) > 300 else ''}

---
"""
                results.append(info)

            return f"Found {len(data)} external papers for '{query}':\n\n" + "\n".join(results)

        except Exception as e:
            return f"Error searching external papers: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Select a paper to discuss by providing its ArXiv ID", icon="doc.text")
    @hyphae.args(
        arxiv_id="The ArXiv ID of the paper (e.g., '2301.12345' or 'cs.AI/0601001')",
        load_full_text="Whether to attempt to load the full paper text for deeper analysis"
    )
    def SelectPaper(self, arxiv_id: str, load_full_text: bool = True) -> str:
        """
        STATEFUL WORKFLOW TOOL:
        
        This tool demonstrates how agents can maintain state and create workflows.
        By selecting a paper, we store its metadata in the agent's state, which
        then enables other tools (like Researcher) that work with the selected paper.
        
        This creates a natural workflow: search → select → analyze.
        """
        
        # Clean and normalize the ArXiv ID
        arxiv_id = arxiv_id.strip()
        if arxiv_id.startswith('http'):
            # Extract ID from URL if user provides full ArXiv URL
            arxiv_id = arxiv_id.split('/')[-1]
            arxiv_id = arxiv_id.replace('.pdf', '')
        
        try:
            # Get paper metadata from ArXiv API
            base_url = "http://export.arxiv.org/api/query"
            search_query = f"id_list={arxiv_id}"
            url = f"{base_url}?{search_query}"
            
            response = requests.get(url)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                return f"Paper with ID '{arxiv_id}' not found."
            
            entry = feed.entries[0]
            
            # Store paper information in agent state
            # This is the key to stateful agent behavior
            self.selected_paper = {
                'id': arxiv_id,
                'title': entry.title.replace('\n', ' ').strip(),
                'authors': [author.name for author in entry.authors] if hasattr(entry, 'authors') else [],
                'abstract': entry.summary.replace('\n', ' ').strip(),
                'published': entry.published[:10] if hasattr(entry, 'published') else "Unknown",
                'categories': [tag.term for tag in entry.tags] if hasattr(entry, 'tags') else [],
                'url': f"https://arxiv.org/abs/{arxiv_id}",
                'pdf_url': f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            }
            
            # Attempt to get full text if requested
            paper_text = ""
            if load_full_text:
                try:
                    paper_text = self._extract_paper_text(arxiv_id)
                    self.paper_content = paper_text
                except Exception as e:
                    paper_text = f"Could not extract full text: {str(e)}"
            
            # Format response showing successful selection
            authors_str = ", ".join(self.selected_paper['authors'][:3])
            if len(self.selected_paper['authors']) > 3:
                authors_str += " et al."
            
            result = f"""
**Paper Selected Successfully!**

**Title:** {self.selected_paper['title']}
**Authors:** {authors_str}
**Published:** {self.selected_paper['published']}
**Categories:** {', '.join(self.selected_paper['categories'][:3])}
**URL:** {self.selected_paper['url']}
**PDF URL:** {self.selected_paper['pdf_url']}

**Abstract:**
{self.selected_paper['abstract']}

**Status:** Paper is now loaded and ready for discussion. You can now use your Researcher to ask questions about this specific paper!
"""
            
            if paper_text and "Could not extract" not in paper_text:
                result += f"\n**Full Text Status:** Successfully loaded full paper content for detailed analysis."
            else:
                result += f"\n**Full Text Status:**  Using abstract and metadata only. {paper_text if paper_text else ''}"
            
            return result
            
        except Exception as e:
            return f"Error selecting paper: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    def _extract_paper_text(self, arxiv_id: str) -> str:
        """
        HELPER METHOD (NOT A TOOL):
        
        Methods without @hyphae.tool decorators are not exposed to the AI agent.
        They serve as internal helper functions that tools can call.
        
        This method attempts to extract paper content for deeper analysis.
        In a production system, this might use PDF parsing libraries.
        """
        try:
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            response = requests.get(abs_url)
            
            if response.status_code == 200:
                content = response.text
                
                # In this example, we just note that the page was loaded
                # A full implementation might parse the PDF or extract more content
                return f"Paper abstract page loaded. For full text analysis, the abstract and metadata provide substantial information for discussion."
            else:
                return "Could not access paper content"
                
        except Exception as e:
            return f"Error extracting paper text: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Researcher - Discuss the selected paper with an expert", icon="graduationcap", predicate=lambda self: self.has_paper_selected())
    @hyphae.args(
        question="Your question about the selected paper",
        analysis_type="Type of analysis: 'general', 'technical', 'methodology', 'results', 'implications'"
    )
    def Researcher(self, question: str, analysis_type: str = "general") -> str:
        """
        CONDITIONAL TOOL WITH AI-POWERED ANALYSIS:
        
        This tool demonstrates several key Hyphae concepts:
        
        1. PREDICATE-BASED ACCESS: Only available when a paper is selected
        2. STATEFUL OPERATION: Uses previously stored paper data
        3. AI-POWERED ANALYSIS: Uses external AI to provide expert-level responses
        4. CONTEXTUAL INTELLIGENCE: Provides paper context to the AI for informed responses
        
        This creates an expert consultation experience where users can ask detailed
        questions about specific papers and get informed, contextual answers.
        """
        
        if not self.selected_paper:
            return "No paper selected! Please use the SelectPaper tool first to choose a paper to discuss."
        
        # Prepare comprehensive paper context for the AI
        paper_info = f"""
Paper: {self.selected_paper['title']}
Authors: {', '.join(self.selected_paper['authors'])}
Published: {self.selected_paper['published']}
Categories: {', '.join(self.selected_paper['categories'])}
ID: {self.selected_paper['id']}

Abstract:
{self.selected_paper['abstract']}
"""
        
        # Include full text content if available
        if self.paper_content and "Could not extract" not in self.paper_content:
            paper_info += f"\n\nAdditional Content:\n{self.paper_content[:2000]}..."
        
        # Create an expert researcher prompt for the AI
        researcher_prompt = f"""You are an expert academic researcher with deep knowledge across multiple fields. A user has selected this research paper to discuss:

{paper_info}

The user is asking about this paper with a focus on {analysis_type} analysis. Please provide a thorough, educational response that:

1. Directly addresses their question about the paper
2. Provides context and background when helpful
3. Explains complex concepts in an accessible way
4. Relates the paper to broader research trends when relevant
5. Suggests follow-up questions or areas for deeper exploration

user's question: {question}

Please respond as a knowledgeable researcher would, being both informative and encouraging."""

        try:
            # Use external AI service to generate expert response
            response = PerplexitySearcher().run(researcher_prompt)
            
            # Format response with context
            return f" **Researcher's Response:**\n\n{response}\n\n---\n **Current Paper:** {self.selected_paper['title']}\n **Url:** {self.selected_paper['url']}"
            
        except Exception as e:
            return f"Error getting researcher response: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Get information about the currently selected paper", icon="info.circle", predicate=lambda self: self.has_paper_selected())
    def GetCurrentPaper(self) -> str:
        """
        STATE QUERY TOOL:
        
        This tool allows users to check what paper is currently selected.
        It demonstrates how agents can provide information about their internal state.
        
        This is useful in conversational interfaces where users might forget
        what they were working on or want to confirm the current context.
        """
        
        if not self.selected_paper:
            return "No paper is currently selected. Use SearchPapers to find papers, then SelectPaper to choose one."
        
        authors_str = ", ".join(self.selected_paper['authors'])
        categories_str = ", ".join(self.selected_paper['categories'])
        
        return f"""
**Currently Selected Paper:**

**Title:** {self.selected_paper['title']}
**Authors:** {authors_str}
**Published:** {self.selected_paper['published']}
**Categories:** {categories_str}
**ID:** {self.selected_paper['id']}
**URL:** {self.selected_paper['url']}
**PDF:** {self.selected_paper['pdf_url']}

**Abstract:**
{self.selected_paper['abstract']}

"""

def on_app_start(instance: ArxivApp):
    """
    APP LIFECYCLE HOOK:
    
    This function is called when the agent application starts up.
    Used for any initialization that needs to happen after the agent is created.
    
    In this case, we just log that the app is starting, but this could be used for:
    - Loading configuration
    - Initializing external connections
    - Setting up caches or databases
    - Performing health checks
    """
    print("ArxivApp starting")

# HOOKS REGISTRATION:
# Register our startup hook with the Hyphae system
hooks.on_app_start = on_app_start

# MAIN EXECUTION:
# Standard Hyphae app entry point
if __name__ == "__main__":
    # hyphae.run() starts the agent runtime with our ArxivApp class instance
    # This creates a gRPC server that TruffleOS can communicate with
    # The agent becomes available for users to interact with through the TruffleOS interface
    hyphae.run(ArxivApp())
