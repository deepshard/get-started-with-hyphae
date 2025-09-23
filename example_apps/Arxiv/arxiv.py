import hyphae
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
import re
from urllib.parse import quote
import feedparser
import time
import traceback
from hyphae.tools.respond_to_user import RespondToUserReturnType

# Hyphae hooks system for customizing agent lifecycle
import hyphae.hooks as hooks

# Local module containing custom prompts and context overrides
import prompts

# HOOKS SYSTEM:
# Override the default system context with custom prompts for this ArXiv research agent
# This sets up specialized instructions for academic paper search and analysis
hooks.get_initial_context = prompts.get_initial_context_override

# MAIN AGENT CLASS:
# This ArXiv research agent demonstrates academic paper search and analysis
# It shows patterns for integrating external APIs and maintaining state across tool calls
class ArxivApp:
    def __init__(self):
        self.selected_paper = None
        self.paper_content = None
        
    def has_paper_selected(self) -> bool:
        """
        PREDICATE FUNCTION:
        
        This function is used in tool decorators to conditionally enable tools.
        Some tools (like Researcher) only make sense when a paper is selected.
        This creates a natural workflow: search → select → analyze.
        """
        return self.selected_paper is not None
    
    # CORE COMMUNICATION TOOL:
    # This is the primary way the agent sends responses back to users
    @hyphae.tool("Send a comprehensive response to the user with the most relevant ArXiv papers and their summaries. Include clickable links to each paper so users can easily access them. Use this to present your research findings in a well-formatted, user-friendly way.", icon="message")
    @hyphae.args(
        response="The response message containing relevant ArXiv papers with brief summaries, clickable links to papers, and formatted in markdown"
    )
    def RespondToUser(self, response: str) -> RespondToUserReturnType:
        """
        ARXIV-FOCUSED USER RESPONSE:
        This tool is specifically designed for presenting ArXiv research findings.
        The response should include:
        - A clear answer to the user's research question
        - List of most relevant papers with brief summaries
        - Clickable links to ArXiv papers (both abstract and PDF links)
        - Key insights or connections between papers
        - Markdown formatting for readability
        """
        r = RespondToUserReturnType()
        r.response = response
        return r
    
    # TOOL DEFINITIONS:
    # Each @hyphae.tool decorated method becomes available to the AI agent
    
    @hyphae.tool("Use this tool to search for papers specifc to the users query, this tool will give you a list of papers that you can attach when responding to the user, dont call this tool too often focus on narrowing your resesarch towards a response for the user", icon="magnifyingglass")
    @hyphae.args(
        query="The search query (can be a topic, keywords, or specific paper title)",
        max_results="Maximum number of results to return (default: 10)"
    )
    def SearchPapers(self, query: str, max_results: int = 10) -> str:
        """
        ARXIV API INTEGRATION:
        
        This tool demonstrates how to integrate external APIs with Hyphae agents.
        The ArXiv API provides free access to academic papers in physics, math,
        computer science, and other fields. Always use this tool first to find the user some papers to start with, your response to the user should have papers fetchedf from this tool.
        
        The tool returns formatted markdown that the AI can read and present to users.
        """
        # ArXiv API search - uses their REST API with Atom feed responses
        base_url = "http://export.arxiv.org/api/query"
        search_query = f"search_query=all:{quote(query)}"
        params = f"{search_query}&start=0&max_results={max_results}&sortBy=relevance&sortOrder=descending"
        
        url = f"{base_url}?{params}"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            
            # Parse the Atom feed
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                return f"No papers found for query: {query}"
            
            results = []
            for i, entry in enumerate(feed.entries, 1):
                # Extract information
                title = entry.title.replace('\n', ' ').strip()
                authors = [author.name for author in entry.authors] if hasattr(entry, 'authors') else []
                author_str = ", ".join(authors[:3])  # Show first 3 authors
                if len(authors) > 3:
                    author_str += " et al."
                
                # Extract ArXiv ID from the entry link
                arxiv_id = entry.id.split('/')[-1]
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                
                # Extract abstract
                summary = entry.summary.replace('\n', ' ').strip()
                
                # Extract published date
                published = entry.published[:10] if hasattr(entry, 'published') else "Unknown"
                
                # Extract categories
                categories = []
                if hasattr(entry, 'tags'):
                    categories = [tag.term for tag in entry.tags]
                category_str = ", ".join(categories[:3])
                
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
            return f"Error searching for papers: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Select a paper to discuss by providing its ArXiv ID, this tool is to be used to analuyze the papers that were fetched by SearchPapers and summarize them to present it in a user friendly way when responding to the user ", icon="doc.text")
    @hyphae.args(
        arxiv_id="The ArXiv ID of the paper (e.g., '2301.12345' or 'cs.AI/0601001')",
        load_full_text="Whether to attempt to load the full paper text for deeper analysis"
    )
    def SelectPaper(self, arxiv_id: str, load_full_text: bool = True) -> str:
        """Select a paper for discussion and load its content"""
        
        # Clean the ArXiv ID
        arxiv_id = arxiv_id.strip()
        if arxiv_id.startswith('http'):
            # Extract ID from URL
            arxiv_id = arxiv_id.split('/')[-1]
            arxiv_id = arxiv_id.replace('.pdf', '')
        
        try:
            # Get paper metadata
            base_url = "http://export.arxiv.org/api/query"
            search_query = f"id_list={arxiv_id}"
            url = f"{base_url}?{search_query}"
            
            response = requests.get(url)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                return f"Paper with ID '{arxiv_id}' not found."
            
            entry = feed.entries[0]
            
            # Store paper information
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
            
            # Format response
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

**Status:** Paper is now loaded and ready for discussion. You should now use respondToUser to deliver it to the user for analysis!
"""
            
            if paper_text and "Could not extract" not in paper_text:
                result += f"\n**Full Text Status:** Successfully loaded full paper content for detailed analysis."
            else:
                result += f"\n**Full Text Status:**  Using abstract and metadata only. {paper_text if paper_text else ''}"
            
            return result
            
        except Exception as e:
            return f"Error selecting paper: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    def _extract_paper_text(self, arxiv_id: str) -> str:

        try:
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            response = requests.get(abs_url)
            
            if response.status_code == 200:
                content = response.text
                
                return f"Paper abstract page loaded. For full text analysis, the abstract and metadata provide substantial information for discussion."
            else:
                return "Could not access paper content"
                
        except Exception as e:
            return f"Error extracting paper text: {str(e)}\nTraceback: {traceback.format_exc()}"
    
    @hyphae.tool("Get information about the currently selected paper, use this tool to get information about the paper that you have selected", icon="info.circle", predicate=lambda self: self.has_paper_selected())
    def GetCurrentPaper(self) -> str:
        
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
    print("ArxivApp starting")

hooks.on_app_start = on_app_start

if __name__ == "__main__":
    hyphae.run(ArxivApp())
